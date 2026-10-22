"""Invoke the unmodified native PinBoard; adapt static placement and alpha only."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

if __name__ == "__main__" and Path(__file__).name == "<stdin>":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--skill-root", required=True, type=Path)
    SKILL = parser.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from overlay_studio_runtime import SOURCE_PIN, check_runtime, probe_runtime, sha

ENTRY = "scripts/overlay_studio_adapter.py"
DEPENDENCY_ID = "overlay-studio-native"
VERSION = "1.0.0"
TEMPLATE_ID = "overlay-studio/pin-board"
RENDERER = "OverlayStudio"
_REUSE_REFS = {"native-pngs", "native-doc", "native-source", "native-evidence"}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value, *, empty=False):
    return (type(value) is str and (empty or bool(value.strip()))
            and len(value) <= 1000 and not any(ord(c) < 32 for c in value))


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
    fields = {"schema_version", "source_binding", "composition", "doc", "layout", "parent_safe_zone",
              "template_request", "assets", "upstream", "execution_mode"}
    if type(b) is not dict or set(b) != fields or type(b["schema_version"]) is not int or b["schema_version"] != 1:
        raise ValueError("Invalid Overlay Studio pin-board brief")
    s, c, doc, layout = (b[k] for k in ("source_binding", "composition", "doc", "layout"))
    if (type(s) is not dict or set(s) != {"aroll_sha256", "segment_id", "start", "end"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(s["aroll_sha256"]))
            or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", str(s["segment_id"]))
            or not all(_number(s[k]) for k in ("start", "end")) or not 0 <= s["start"] < s["end"]):
        raise ValueError("Invalid PinBoard source binding")
    if (type(c) is not dict or set(c) != {"width", "height", "fps", "frames", "alpha"}
            or any(type(c[k]) is not int or c[k] != v for k, v in (("width",1080),("height",1920),("fps",24)))
            or type(c["frames"]) is not int or c["frames"] < 1 or c["alpha"] is not True
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("PinBoard requires the exact approved portrait frame clock")
    if (type(doc) is not dict or not {"version", "theme", "cards"} <= set(doc)
            or set(doc) - {"version", "theme", "font", "inkColor", "glow", "breath", "cam", "cards"}
            or doc["version"] != 1 or doc["theme"] not in {"light", "dark"}
            or doc.get("cam") not in (None, "") or doc.get("glow", False) is not False
            or doc.get("breath", False) is not False):
        raise ValueError("Unsupported native OverlayDoc fields or additional layers")
    if "font" in doc and not _text(doc["font"]):
        raise ValueError("Invalid native font")
    if "inkColor" in doc and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(doc["inkColor"])):
        raise ValueError("Invalid native inkColor")
    if type(doc["cards"]) is not list or len(doc["cards"]) != 1:
        raise ValueError("Only one native pin-board is connected")
    card = doc["cards"][0]
    if (type(card) is not dict or set(card) != {"id", "kind", "start", "end", "params"}
            or not _text(card["id"]) or card["kind"] != "pin-board"
            or not all(_number(card[k]) for k in ("start", "end"))
            or not 0 <= card["start"] < card["end"] <= c["frames"] / 24 + 1e-8):
        raise ValueError("Native card.start/end must be seconds within the voice window")
    params = card["params"]
    allowed = {"theme", "position", "title", "subtitle", "items", "times", "stepMs",
               "accent", "offsetX", "offsetY", "scale", "speed", "sfx"}
    if (type(params) is not dict or set(params) - allowed
            or params.get("sfx") != "none" or params.get("speed", 1) != 1
            or params.get("title", "") != "" or params.get("subtitle", "") != ""
            or params.get("position") not in {"top-left", "top-right"}
            or params.get("theme") not in {"light", "dark"}
            or params.get("accent") not in {"orange", "blue", "alert"}):
        raise ValueError("Unsupported PinBoard parameters, title, subtitle, or sound")
    for key in ("offsetX", "offsetY", "scale", "stepMs", "speed"):
        if key in params and not _number(params[key]):
            raise ValueError("Invalid native numeric parameter: " + key)
    if params.get("scale", 1) <= 0 or params.get("stepMs", 4000) <= 0:
        raise ValueError("Invalid native scale or stepMs")
    if not _text(params.get("items")) or not _text(params.get("times")):
        raise ValueError("Explicit native items and times are required")
    items = params["items"].split("|")
    if any(not _text(x) or x != x.strip() for x in items):
        raise ValueError("Native items must be separate nonempty short labels")
    try:
        times = [float(x) for x in params["times"].split("|")]
    except ValueError:
        raise ValueError("Invalid native times") from None
    if (len(times) != len(items) or any(not math.isfinite(t) or t < 0 for t in times)
            or any(a >= z for a, z in zip(times, times[1:]))
            or times[-1] + 0.34 > card["end"] - card["start"] - 0.45 + 1e-8):
        raise ValueError("Each item needs its own time and a complete native landing/exit")
    if type(layout) is not dict or set(layout) != {"crop", "placement"}:
        raise ValueError("PinBoard needs one fixed crop and placement")
    crop, place = layout["crop"], layout["placement"]
    for box, width, height in ((crop,1920,1080),(place,1080,1920)):
        if (type(box) is not dict or set(box) != {"x","y","width","height"}
                or any(type(box[k]) is not int for k in box)
                or min(box["x"],box["y"]) < 0 or min(box["width"],box["height"]) <= 0
                or box["x"]+box["width"] > width or box["y"]+box["height"] > height):
            raise ValueError("Invalid fixed crop or placement")
    if crop["width"] * place["height"] != crop["height"] * place["width"]:
        raise ValueError("PinBoard placement must preserve aspect ratio")
    zone = b["parent_safe_zone"]
    if (type(zone) is not dict or set(zone) != {"top", "bottom", "left", "right"}
            or any(type(value) is not int or value < 0 for value in zone.values())
            or zone["left"] + zone["right"] >= c["width"]
            or zone["top"] + zone["bottom"] >= c["height"]):
        raise ValueError("PinBoard requires the actual parent safe-zone margins")
    request = b["template_request"]
    if request != {"semantic_family":"cumulative_points", "information_units":len(items),
                   "numeric_values":[], "numeric_scale":"not_applicable"}:
        raise ValueError("PinBoard template request must describe the actual short points")
    if (type(b["upstream"]) is not dict or set(b["upstream"]) != {"source_revision","runtime_identity"}
            or b["upstream"]["source_revision"] != SOURCE_PIN
            or not re.fullmatch(r"[a-f0-9]{64}", str(b["upstream"]["runtime_identity"]))):
        raise ValueError("PinBoard upstream identity missing")
    assets = b["assets"]
    if type(assets) is not list or len(assets) > 4:
        raise ValueError("Invalid PinBoard frozen assets")
    for record in assets:
        if type(record) is not dict or set(record) != {"media_ref","job_path","sha256"}:
            raise ValueError("Invalid frozen native file")
        path = PurePosixPath(record["job_path"])
        if (not record["job_path"] or path.is_absolute() or ".." in path.parts
                or path.as_posix() != record["job_path"]
                or not re.fullmatch(r"[a-f0-9]{64}", str(record["sha256"]))):
            raise ValueError("Invalid native asset path or digest")
    refs = [a["media_ref"] for a in assets]
    if (len(refs) != len(set(refs)) or len({a["job_path"] for a in assets}) != len(assets)
            or b["execution_mode"] not in {"native_export","reuse_png"}
            or (b["execution_mode"] == "native_export" and assets)
            or (b["execution_mode"] == "reuse_png" and set(refs) != _REUSE_REFS)):
        raise ValueError("Execution mode must explicitly choose native export or frozen PNG reuse")
    return b


def validate_parent_layout(brief, component):
    """The brief carries a snapshot, never a separate layout authority."""
    if (brief["parent_safe_zone"] != component["render_window"]["safe_zone"]
            or any(brief["composition"][key] != component["artifact_contract"][key]
                   for key in ("width", "height"))):
        raise ValueError("PinBoard layout differs from the approved parent safe zone or canvas")


def validate_visible_bounds(bounds, brief):
    """Check the complete native action under the same crop/placement as conversion."""
    crop, place = brief["layout"]["crop"], brief["layout"]["placement"]
    if not bounds or not (crop["x"] <= bounds[0] and crop["y"] <= bounds[1]
                         and crop["x"] + crop["width"] >= bounds[2]
                         and crop["y"] + crop["height"] >= bounds[3]):
        raise ValueError("Fixed crop does not contain the complete native action and shadows")
    # Integer floor/ceil plus two pixels for the scale filter's edge sampling.
    left = place["x"] + (bounds[0] - crop["x"]) * place["width"] // crop["width"] - 2
    top = place["y"] + (bounds[1] - crop["y"]) * place["height"] // crop["height"] - 2
    right = place["x"] + ((bounds[2] - crop["x"]) * place["width"] + crop["width"] - 1) // crop["width"] + 2
    bottom = place["y"] + ((bounds[3] - crop["y"]) * place["height"] + crop["height"] - 1) // crop["height"] + 2
    zone, canvas = brief["parent_safe_zone"], brief["composition"]
    safe = (zone["left"], zone["top"], canvas["width"] - zone["right"], canvas["height"] - zone["bottom"])
    if left < safe[0] or top < safe[1] or right > safe[2] or bottom > safe[3]:
        raise ValueError(f"PinBoard complete action {(left, top, right, bottom)} exceeds parent safe rectangle {safe}")
    return left, top, right, bottom


def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project)
    entry_sha = sha(SKILL / ENTRY)
    python = Path(python_executable).resolve(strict=True)

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if sha(SKILL / ENTRY) != entry_sha or check_runtime(project, runtime)["identity"] != runtime["identity"]:
            raise ValueError("Overlay Studio adapter or runtime changed")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        ar = visual_canary.approved_aroll_record(job, plan)
        expected = dict(aroll_sha256=ar["sha256"], segment_id=segment["segment_id"],
                        start=segment["start"], end=segment["end"])
        if (b["source_binding"] != expected or b["upstream"]["runtime_identity"] != runtime["identity"]
                or json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or recipe["composition"]["family"] != "aroll_with_overlay"
                or component["layer_role"] != "annotation"
                or component["artifact_contract"] != {"width":1080,"height":1920,"fps":24,"alpha":True}
                or component["render_window"]["start_frame"] != 0
                or component["render_window"]["end_frame"] != b["composition"]["frames"]
                or component["source_sha256"] != entry_sha
                or json.loads(json.dumps(component["invocation_record"]["template_request"])) != b["template_request"]):
            raise ValueError("PinBoard input differs from the approved A-roll shot")
        validate_parent_layout(b, component)
        return payload

    def media(job, recipe, component, payload):
        return tuple(ReferenceProcessMedia(**record) for record in validate_brief(payload)["assets"])

    return ReferenceProcessAdapter(adapter_id="overlay-studio-pinboard-v1",
        dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter", dependency_root=SKILL,
        entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION,
        primary_renderer=RENDERER, renderer_version=VERSION, artifact_media_type="video",
        launcher=python, launcher_sha256=sha(python), brief_loader=guard, media_loader=media,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=("{launcher}","{entrypoint}","--skill-root",str(SKILL),
                       "--project-root",str(project),"--brief","{brief_path}",
                       "--media-manifest","{media_manifest_fd}","--output","{output_path}",
                       "--runtime-identity",runtime["identity"],
                       "--node",runtime["node"],"--ffmpeg",runtime["ffmpeg"],
                       "--ffprobe",runtime["ffprobe"],"--chrome",runtime["chrome"]))


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    if (adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != sha(SKILL / ENTRY)
            or adapter.entrypoint != ENTRY or adapter.primary_renderer != RENDERER):
        raise ValueError("PinBoard adapter identity changed")
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return dict(producer_type="dependency", dependency_id=DEPENDENCY_ID, entrypoint=ENTRY,
        producer_version=VERSION, primary_renderer=RENDERER, renderer_version=VERSION,
        template_origin="custom_fallback", template_id=TEMPLATE_ID, template_version=VERSION,
        adaptation_level="structural", source_entrypoint=ENTRY, source_sha256=adapter.entrypoint_sha256,
        sample_sha256=sha(Path(reference_sample)), semantic_families=["cumulative_points"],
        capacity={"min_units":b["template_request"]["information_units"],
                  "max_units":b["template_request"]["information_units"]},
        brief_sha256=digest, verification_id=hashlib.sha256((adapter.entrypoint_sha256+digest).encode()).hexdigest(),
        invocation_record={"argv":[str(adapter.launcher),ENTRY],"status":"planned","exit_code":None,
                           "template_request":b["template_request"]})


def create_artifact_probe(ffprobe_executable):
    from hyperframes_hw_pipeline_adapter import create_artifact_probe as alpha_probe
    return alpha_probe(ffprobe_executable=ffprobe_executable)


def _frozen_assets(args, brief, directory, brief_bytes):
    manifest = json.loads(Path(args.media_manifest).read_bytes())
    if manifest.get("schema_version") != "reference-process-media/v1" or manifest.get("brief_sha256") != hashlib.sha256(brief_bytes).hexdigest():
        raise ValueError("PinBoard media manifest differs from frozen brief")
    records = {x["media_ref"]:x for x in manifest["media"]}
    if len(records) != len(manifest["media"]) or set(records) != {a["media_ref"] for a in brief["assets"]}:
        raise ValueError("PinBoard frozen media set differs")
    result = {}
    for asset in brief["assets"]:
        record = records[asset["media_ref"]]
        data = Path("/dev/fd/" + str(record["fd"])).read_bytes()
        if len(data) != record["byte_length"] or hashlib.sha256(data).hexdigest() != asset["sha256"] or record["sha256"] != asset["sha256"]:
            raise ValueError("PinBoard frozen media changed")
        target = directory / asset["media_ref"]
        target.write_bytes(data)
        result[asset["media_ref"]] = target
    return result


def _reuse_frames(files, brief, directory):
    original = json.loads(files["native-doc"].read_bytes())
    source = json.loads(files["native-source"].read_bytes())
    evidence = json.loads(files["native-evidence"].read_bytes())
    s = brief["source_binding"]
    if (original != brief["doc"] or source.get("source_sha256") != s["aroll_sha256"]
            or source.get("segment_id") != s["segment_id"]
            or source.get("body_start") != s["start"] or source.get("body_end") != s["end"]
            or source.get("browser_user_authorized") is not True
            or evidence.get("status") != "ready_for_visual_review"
            or evidence.get("native",{}).get("ok") is not True
            or evidence["native"]["frames"] != brief["composition"]["frames"]
            or evidence["native"]["fps"] != 24):
        raise ValueError("Existing native PNGs do not describe this exact document/source/window")
    frames = directory / "frames"
    frames.mkdir()
    expected = [f"frame_{i:06d}.png" for i in range(1, brief["composition"]["frames"]+1)]
    with zipfile.ZipFile(files["native-pngs"]) as archive:
        if (archive.namelist() != expected or sum(x.file_size for x in archive.infolist()) > 512*1024*1024):
            raise ValueError("Native PNG archive has missing, extra, or excessive content")
        for name in expected:
            (frames / name).write_bytes(archive.read(name))
    return frames


def _native_export(brief, runtime, directory, run, environment):
    app = directory / "native-app"
    shutil.copytree(Path(runtime["vendor"]) / "motion-playground", app,
                    ignore=shutil.ignore_patterns("node_modules","exports","_fxframes","_media"))
    (app / "node_modules").symlink_to(Path(runtime["root"]) / "node_modules", target_is_directory=True)
    with socket.socket() as connection:
        if connection.connect_ex(("127.0.0.1",5177)) == 0:
            raise ValueError("Native service port occupied; no automatic attachment or retry")
    job = directory / "native-job.json"
    job.write_text(json.dumps({"doc":brief["doc"],"fps":24,"duration":brief["composition"]["frames"]/24,
                               "base":"http://127.0.0.1:5177","keepFrames":True}, ensure_ascii=False))
    doc = directory / "overlay.json"
    doc.write_text(json.dumps(brief["doc"],ensure_ascii=False))
    run([runtime["node"],str(Path(runtime["root"])/"node_modules/tsx/dist/cli.mjs"),
         "--tsconfig",str(app/"tsconfig.app.json"),str(app/"scripts/lint-overlay.ts"),str(doc),
         "--duration",str(brief["composition"]["frames"]/24)], app)
    with (directory/"service.log").open("w") as log:
        service = subprocess.Popen([runtime["node"],str(Path(runtime["root"])/"node_modules/vite/bin/vite.js"),
                                    "--host","127.0.0.1","--port","5177","--strictPort"],
                                   cwd=app,env=environment,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if service.poll() is not None:
                    raise ValueError("Native server exited; see retained service.log")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:5177",timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Native server not ready; stopped without retry")
            result = run([runtime["node"],str(app/"scripts/export-frames.mjs"),str(job)], app)
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait()
    native = json.loads(result.stdout.strip().splitlines()[-1])
    if not native.get("ok") or native.get("frames") != brief["composition"]["frames"] or native.get("fps") != 24:
        raise ValueError("Native export returned the wrong frame clock")
    frames = Path(native["dir"]).resolve(strict=True)
    if not frames.is_relative_to(app.resolve()):
        raise ValueError("Native export escaped its private working directory")
    return frames


def convert_frames(frames, brief, target, runtime, run):
    from PIL import Image
    c, crop, place = brief["composition"], brief["layout"]["crop"], brief["layout"]["placement"]
    files = sorted(frames.glob("frame_*.png"))
    if [x.name for x in files] != [f"frame_{i:06d}.png" for i in range(1,c["frames"]+1)]:
        raise ValueError("Native PNG frame sequence is incomplete")
    union = None
    for path in files:
        with Image.open(path) as image:
            if image.mode != "RGBA" or image.size != (1920,1080):
                raise ValueError("Native PNG must retain the complete straight-alpha stage")
            box = image.getchannel("A").point(lambda value:255 if value>4 else 0).getbbox()
        if box:
            if box[0] == 0 or box[1] == 0 or box[2] == 1920 or box[3] == 1080:
                raise ValueError("Native content touches stage edge; possible upstream clipping")
            union = box if union is None else (min(union[0],box[0]),min(union[1],box[1]),
                                                max(union[2],box[2]),max(union[3],box[3]))
    validate_visible_bounds(union, brief)
    graph = (f'crop={crop["width"]}:{crop["height"]}:{crop["x"]}:{crop["y"]},format=rgba,'
             f'scale={place["width"]}:{place["height"]},'
             f'pad=1080:1920:{place["x"]}:{place["y"]}:color=0x00000000,setsar=1')
    run([runtime["ffmpeg"],"-v","error","-nostdin","-threads","1","-framerate","24",
         "-i",str(frames/"frame_%06d.png"),"-vf",graph,"-frames:v",str(c["frames"]),
         "-an","-c:v","qtrle","-pix_fmt","argb",str(target)], frames.parent)
    media = create_artifact_probe(runtime["ffprobe"]).probe(target,"video",
                  {"width":1080,"height":1920,"fps":24,"alpha":True})
    if media["frame_count"] != c["frames"] or abs(media["duration"] - c["frames"]/24)>1e-6:
        raise ValueError("Converted transparent output has a different frame clock")
    return union


def render(args):
    sys.path.insert(0,str(Path(args.project_root).resolve(strict=True)))
    from project_python import project_environment
    _, packages = project_environment(Path(args.project_root))
    sys.path.insert(0, str(packages))
    brief_bytes = Path(args.brief).read_bytes()
    brief = validate_brief(brief_bytes)
    runtime = check_runtime(args.project_root,{k:getattr(args,k) for k in ("node","ffmpeg","ffprobe","chrome")})
    directory = Path(tempfile.mkdtemp(prefix="overlay-studio-native-"))
    report = {"status":"preparing","execution_mode":brief["execution_mode"],"commands":[]}
    environment = {k:v for k,v in os.environ.items() if k in {"HOME","TMPDIR","LANG"}}
    environment.update(PATH=os.pathsep.join(dict.fromkeys([*(str(Path(runtime[k]).parent)
                       for k in ("node","ffmpeg","ffprobe")),"/usr/bin","/bin"])),
                       BROWSER="none",PUPPETEER_SKIP_DOWNLOAD="true",
                       PUPPETEER_EXECUTABLE_PATH=runtime["chrome"])
    def run(command, cwd):
        record={"argv":command,"exit_code":None}
        report["commands"].append(record)
        result=subprocess.run(command,cwd=cwd,env=environment,capture_output=True,text=True,timeout=360)
        record.update(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
        result.check_returncode()
        return result
    try:
        if args.runtime_identity != runtime["identity"] or brief["upstream"]["runtime_identity"] != runtime["identity"]:
            raise ValueError("Bound Overlay Studio runtime changed")
        assets=_frozen_assets(args,brief,directory,brief_bytes)
        frames=(_reuse_frames(assets,brief,directory) if brief["execution_mode"]=="reuse_png"
                else _native_export(brief,runtime,directory,run,environment))
        target=directory/"overlay.mov"
        bounds=convert_frames(frames,brief,target,runtime,run)
        # Only the executor's pinned destination receives the complete result.
        with target.open("rb") as source, Path(args.output).open("wb") as destination:
            shutil.copyfileobj(source,destination)
        result=dict(report,status="completed",frames=brief["composition"]["frames"],
                    native_export_invoked=brief["execution_mode"]=="native_export",
                    upstream_revision=SOURCE_PIN,runtime_identity=runtime["identity"],
                    native_visible_bounds=bounds,output_sha256=sha(target),
                    normalization="fixed crop/place; lossless QTRLE straight alpha; no new motion")
    except Exception as error:
        report.update(status="failed",error_type=type(error).__name__,error=str(error))
        failure=directory/"failure.json"
        failure.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        raise RuntimeError("Overlay Studio stopped without retry; inspect "+str(failure)) from error
    shutil.rmtree(directory)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root",required=True,type=Path)
    parser.add_argument("--skill-root",type=Path)
    parser.add_argument("--probe",action="store_true")
    for key in ("brief","media-manifest","output","runtime-identity","node","ffmpeg","ffprobe","chrome"):
        parser.add_argument("--"+key)
    args=parser.parse_args()
    if args.probe:
        sys.path.insert(0,str(args.project_root.resolve(strict=True)))
        adapter=create_adapter(args.project_root,sys.executable,lambda *_:b"")
        probe_runtime(args.project_root)
        print(json.dumps(dict(schema_version=1,dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,
                              producer_version=VERSION,adapter_identity=dict(
                              adapter_type=type(adapter).__name__,approved_executor="reference_adapter",
                              primary_renderer=RENDERER)),ensure_ascii=False))
    elif args.brief and args.output and args.media_manifest:
        print(json.dumps(render(args),ensure_ascii=False))
    else:
        parser.error("choose --probe or the complete frozen execution arguments")

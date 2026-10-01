"""Execute reviewed upstream-authored scenes; never generate animation code here."""
from __future__ import annotations

import argparse
import base64
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parent.parent
ENTRY = "scripts/upstream_scene_adapter.py"
VERSION = "1.0.0"
ONETAKE_PACKAGES = {"playwright": "1.61.0", "numpy": "2.5.3", "Pillow": "12.3.0",
                    "scipy": "1.18.1", "matplotlib": "3.11.2", "fonttools": "4.66.1", "brotli": "1.2.0"}
SOURCES = {
    "lemo-opuscar": ("f3c590dffab39419e2f3018416706e046986fe11", "core/render/video.mjs"),
    "onetake": ("cf09bde3e392c9aa32c4157f80cdbe1fa556685e", "scripts/render.py"),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError("A nonempty relative path is required")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Scene assets must have canonical relative paths")
    return path


def validate_brief(payload):
    b = json.loads(payload)
    if (type(b) is not dict or set(b) != {"schema_version", "dependency_id", "source_binding",
            "template_request", "composition", "files", "workflow_media_ref"}
            or b["schema_version"] != 1 or b["dependency_id"] not in SOURCES):
        raise ValueError("Invalid upstream scene brief")
    s, c, request = b["source_binding"], b["composition"], b["template_request"]
    if (set(s) != {"aroll_sha256", "segment_id", "start", "end"}
            or not re.fullmatch(r"[a-f0-9]{64}", s["aroll_sha256"])
            or not re.fullmatch(r"seg-[a-zA-Z0-9_-]+", s["segment_id"])
            or any(type(s[k]) not in (int, float) or not math.isfinite(s[k]) for k in ("start", "end"))
            or not 0 <= s["start"] < s["end"]):
        raise ValueError("Invalid upstream source clock")
    if (set(c) != {"id", "width", "height", "fps", "frames"}
            or not re.fullmatch(r"[a-zA-Z0-9_-]+", c["id"])
            or (c["width"], c["height"], c["fps"]) != (1080, 1920, 24)
            or type(c["frames"]) is not int or not 1 <= c["frames"] <= 1440
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Upstream scene must match the approved portrait frame clock")
    if (set(request) != {"semantic_family", "information_units", "numeric_values", "numeric_scale"}
            or not isinstance(request["semantic_family"], str) or not request["semantic_family"]
            or type(request["information_units"]) is not int or request["information_units"] < 1
            or type(request["numeric_values"]) is not list
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in request["numeric_values"])
            or request["numeric_scale"] not in (("linear", "log") if request["numeric_values"] else ("not_applicable",))
            or (request["numeric_scale"] == "log" and any(v <= 0 for v in request["numeric_values"]))):
        raise ValueError("Invalid current semantic or numeric request")
    files = b["files"]
    if type(files) is not list or not 2 <= len(files) <= 8:
        raise ValueError("Freeze 2 to 8 scene files, including the workflow record")
    for f in files:
        if (set(f) != {"media_ref", "job_path", "scene_path", "sha256"}
                or not re.fullmatch(r"[a-zA-Z0-9_-]+", f["media_ref"])
                or not re.fullmatch(r"[a-f0-9]{64}", f["sha256"])):
            raise ValueError("Invalid scene file identity")
        relative(f["job_path"])
        relative(f["scene_path"])
        if Path(f["scene_path"]).parts[0] in {"native.mp4", "artifact.mp4", "_frames"}:
            raise ValueError("Scene assets must not occupy native renderer output paths")
    if (len({f["media_ref"] for f in files}) != len(files)
            or len({f["scene_path"] for f in files}) != len(files)
            or "index.html" not in {f["scene_path"] for f in files}
            or b["workflow_media_ref"] not in {f["media_ref"] for f in files}):
        raise ValueError("Scene entry and distinct workflow record are required")
    return b


def check_runtime(project_root, dependency_id):
    commit, entry = SOURCES[dependency_id]
    project = Path(project_root).resolve(strict=True)
    sys.path.insert(0, str(project))
    from edit.hd.tools import broll_component_executor
    if (Path(broll_component_executor.__file__).resolve().parent != project / "edit/hd/tools"
            or broll_component_executor._DEPENDENCY_CONTRACTS.get(dependency_id) != ("reference_adapter", "HTMLCanvas")):
        raise ValueError("The project execution runtime must register this upstream dependency first")
    root = project / "skill-development/vendor" / dependency_id
    if root.is_symlink():
        raise ValueError("Upstream source must be project-local, not linked")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True)
    if head != commit or dirty:
        raise ValueError("Upstream source version changed; do not auto-update or reset it")
    executables = {name: shutil.which(name) for name in ("node", "ffmpeg", "ffprobe")}
    if any(not value for value in executables.values()):
        raise ValueError("Install the required local Node and video runtime first")
    runtime = {"root": str(root), "commit": commit, "entry": entry, "entry_sha256": sha(root / entry),
               **{name: str(Path(value).resolve()) for name, value in executables.items()}}
    if dependency_id == "lemo-opuscar":
        package = root / "node_modules/playwright-core/package.json"
        runtime["packages_sha256"] = sha(package)
        runtime["browser"] = str(Path(project_root).resolve() / ".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell")
    else:
        # Preserve the venv executable path: resolving its symlink would discard the venv.
        runtime["python"] = str(root / ".venv/bin/python")
        probe = subprocess.check_output([runtime["python"], "-c",
            "import json,sys,importlib.metadata as m; from playwright.sync_api import sync_playwright; "
            "p=sync_playwright().start(); print(json.dumps({'browser':p.chromium.executable_path,"
            "'python':list(sys.version_info[:2]),"
            "'packages':{k:m.version(k) for k in ['playwright','numpy','Pillow','scipy','matplotlib','fonttools','brotli']}})); p.stop()"], text=True)
        details = json.loads(probe)
        if details["python"] != [3, 12] or details["packages"] != ONETAKE_PACKAGES:
            raise ValueError("OneTake requires the approved Python 3.12 render package versions")
        runtime["browser"] = details["browser"]
        runtime["packages_sha256"] = hashlib.sha256(json.dumps(details["packages"], sort_keys=True).encode()).hexdigest()
        runtime["browser_cache"] = str(next(p.parent for p in Path(details["browser"]).parents if p.name.startswith("chromium-")))
    if not Path(runtime["browser"]).is_file():
        raise ValueError("The upstream render browser is missing")
    runtime["executable_hashes"] = {name: sha(runtime[name]) for name in ("node", "ffmpeg", "ffprobe", "browser")}
    if "python" in runtime:
        runtime["executable_hashes"]["python"] = sha(runtime["python"])
    return runtime


def create_adapter(project_root, dependency_id, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    launcher = Path(python_executable).resolve(strict=True)
    runtime = check_runtime(project, dependency_id)
    entry_sha, launcher_sha = sha(SKILL / ENTRY), sha(launcher)

    def check():
        if sha(SKILL / ENTRY) != entry_sha or sha(launcher) != launcher_sha or check_runtime(project, dependency_id) != runtime:
            raise ValueError("Bound upstream implementation or runtime changed")

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary
        check()
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan["segments"] if s["segment_id"] == recipe["segment_id"])
        arroll = visual_canary.approved_aroll_record(job, plan)
        expected = {"aroll_sha256": arroll["sha256"], "segment_id": segment["segment_id"], "start": segment["start"], "end": segment["end"]}
        if (b["dependency_id"] != dependency_id or json.loads(json.dumps(recipe)) != segment["shot_recipe"]
                or b["source_binding"] != expected or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or component["invocation_record"].get("production_evidence") != workflow_reference(b)
                or component["source_sha256"] != entry_sha or component["template_origin"] != "custom_fallback"
                or component["artifact_contract"] != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or component["render_window"]["start_frame"] != 0 or component["render_window"]["end_frame"] != b["composition"]["frames"]):
            raise ValueError("Upstream scene no longer matches the approved source, request or recipe")
        return payload

    def media_loader(job, recipe, component, payload):
        check()
        return tuple(ReferenceProcessMedia(media_ref=f["media_ref"], job_path=f["job_path"], sha256=f["sha256"])
                     for f in validate_brief(payload)["files"])

    return ReferenceProcessAdapter(adapter_id=dependency_id + "-scene-v1", dependency_id=dependency_id,
        approved_executor="reference_adapter", dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer="HTMLCanvas",
        renderer_version=runtime["commit"], artifact_media_type="video", launcher=launcher, launcher_sha256=launcher_sha,
        brief_loader=guarded_loader, media_loader=media_loader, self_contained_wrapper=True,
        timeout_seconds=300, argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
            "--media-manifest", "{media_manifest_fd}", "--runtime", base64.b64encode(json.dumps(runtime, sort_keys=True).encode()).decode(), "--output", "{output_path}"))


def workflow_reference(b):
    f = next(f for f in b["files"] if f["media_ref"] == b["workflow_media_ref"])
    return {"dependency_id": b["dependency_id"], "upstream_commit": SOURCES[b["dependency_id"]][0],
            "workflow_path": f["job_path"], "workflow_sha256": f["sha256"]}


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    if adapter.dependency_id != b["dependency_id"] or adapter.entrypoint_sha256 != sha(SKILL / ENTRY):
        raise ValueError("Upstream scene adapter identity mismatch")
    request = b["template_request"]
    return {"producer_type": "dependency", "dependency_id": adapter.dependency_id, "entrypoint": ENTRY,
        "producer_version": VERSION, "primary_renderer": "HTMLCanvas", "renderer_version": adapter.renderer_version,
        "template_origin": "custom_fallback", "template_id": adapter.dependency_id + "-reviewed-scene", "template_version": VERSION,
        "verification_id": hashlib.sha256((adapter.entrypoint_sha256 + adapter.renderer_version + hashlib.sha256(brief_bytes).hexdigest()).encode()).hexdigest(),
        "adaptation_level": "structural", "source_entrypoint": ENTRY, "source_sha256": adapter.entrypoint_sha256,
        "sample_sha256": sha(reference_sample), "semantic_families": [request["semantic_family"]],
        "capacity": {"min_units": request["information_units"], "max_units": request["information_units"]},
        "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
        "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None,
            "template_request": request, "production_evidence": workflow_reference(b)}}


def create_artifact_probe(ffprobe_executable):
    from whiteboard_adapter import create_artifact_probe as silent_portrait_probe
    return silent_portrait_probe(ffprobe_executable)


def validate_workflow(b, scene, root):
    f = next(f for f in b["files"] if f["media_ref"] == b["workflow_media_ref"])
    w = json.loads((scene / f["scene_path"]).read_bytes())
    if (w.get("dependency_id") != b["dependency_id"] or w.get("upstream_commit") != SOURCES[b["dependency_id"]][0]
            or not all(w.get(k) for k in ("instructions", "concept", "beat_sheet", "upstream_features", "qa"))):
        raise ValueError("Actual upstream production workflow is required, not a renderer-only claim")
    for name in w["instructions"]:
        if not (root / relative(name)).is_file():
            raise ValueError("Selected upstream instruction is missing")
    text = "\n".join((scene / f["scene_path"]).read_text() for f in b["files"] if Path(f["scene_path"]).suffix in {".html", ".js", ".mjs"})
    for feature in w["upstream_features"]:
        source = root / relative(feature["path"])
        if not source.is_file() or not feature.get("usage") or not feature.get("symbol") or feature["symbol"] not in text:
            raise ValueError("Workflow must identify upstream capabilities actually used in this scene")
    if b["dependency_id"] == "onetake":
        if not (scene / "motion.js").is_file() or sha(scene / "motion.js") != sha(root / "lib/motion.js"):
            raise ValueError("OneTake requires its original motion library, unchanged")
    # Reviewed scene code is trusted input, not a JavaScript sandbox. Network/asset
    # completeness is additionally checked in the browser and by the parent QA.
    if re.search(r"https?://|\bfetch\s*\(|<audio\b|\bnew\s+Audio\b", text, re.I):
        raise ValueError("Freeze local assets; upstream B-roll must be silent and offline")


def run_native(b, scene, runtime):
    dependency_id = b["dependency_id"]
    root = Path(runtime["root"])
    commit, entry = SOURCES[dependency_id]
    if runtime["commit"] != commit or runtime["entry"] != entry or sha(root / entry) != runtime["entry_sha256"]:
        raise ValueError("Original render entry changed")
    if subprocess.check_output(["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() != commit:
        raise ValueError("Upstream source commit changed")
    if subprocess.check_output(["/usr/bin/git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True):
        raise ValueError("Upstream tracked source changed")
    if any(sha(runtime[k]) != v for k, v in runtime["executable_hashes"].items()):
        raise ValueError("Render executable changed")
    if dependency_id == "lemo-opuscar" and sha(root / "node_modules/playwright-core/package.json") != runtime["packages_sha256"]:
        raise ValueError("Upstream browser package changed")
    validate_workflow(b, scene, root)
    duration = b["composition"]["frames"] / 24
    env = dict(os.environ, PATH=":".join({str(Path(runtime[k]).parent) for k in ("node", "ffmpeg", "ffprobe")}) + ":/usr/bin:/bin")
    native = scene / "native.mp4"
    if dependency_id == "lemo-opuscar":
        env["PLAYWRIGHT_CHROME"] = runtime["browser"]
        guard = """const {openDemo,closeServer}=await import(process.argv[1]);
const {browser,page}=await openDemo(process.argv[2],{w:1080,h:1920});
const errors=[]; page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
const d=await page.evaluate(()=>({d:window.DUR,r:typeof window.render,ready:window.READY}));
if(d.d!==Number(process.argv[3])||d.r!=='function'||d.ready!==true)throw Error('scene protocol/clock mismatch');
for(const t of [0,d.d/2,d.d-1/24])await page.evaluate(t=>window.render(t),t);
if(errors.length)throw Error(errors.join(';')); await browser.close();closeServer();"""
        subprocess.run([runtime["node"], "--input-type=module", "-e", guard, (root / "core/render/page.mjs").as_uri(), str(scene), str(duration)],
                       cwd=root, env=env, check=True, timeout=210, capture_output=True, text=True)
        argv = [runtime["node"], str(root / entry), str(scene), "--size", "1080x1920", "--fps", "24", "--workers", "1", "--out", str(native)]
    else:
        env["PLAYWRIGHT_BROWSERS_PATH"] = runtime["browser_cache"]
        guard = """import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(); page=b.new_page(viewport={'width':1080,'height':1920}); errors=[]
 page.on('pageerror',lambda e: errors.append(str(e)))
 page.on('console',lambda m: errors.append(m.text) if m.type=='error' else None)
 page.on('requestfailed',lambda r: errors.append(r.url))
 page.goto(sys.argv[1]); page.evaluate('window.__ready')
 d=page.evaluate('({dur:window.__meta?.dur,seek:typeof window.__seek,ready:typeof window.__ready?.then})')
 assert d['dur']==float(sys.argv[2]) and d['seek']=='function' and d['ready']=='function', 'scene protocol/clock mismatch'
 for t in [0,d['dur']/2,d['dur']-1/24]: page.evaluate('(t)=>window.__seek(t)',t)
 assert not errors, errors
 b.close()
"""
        subprocess.run([runtime["python"], "-c", guard, (scene / "index.html").as_uri(), str(duration)], env=env, check=True, timeout=60, capture_output=True, text=True)
        argv = [runtime["python"], str(root / entry), str(scene / "index.html"), "--width", "1080", "--height", "1920", "--fps", "24", "--dur", str(duration), "--workers", "1", "--out", str(native)]
    result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, check=True, timeout=240)
    log = result.stdout + result.stderr
    if (dependency_id == "onetake" and "page errors: none" not in log) or re.search(r"\[page(?:error)?\]|request failed|optional file missing", log):
        raise ValueError("Native renderer reported scene or missing-asset errors")
    probe = json.loads(subprocess.check_output([runtime["ffprobe"], "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(native)], text=True))
    streams = probe["streams"]
    if (len(streams) != 1 or streams[0]["codec_type"] != "video"
            or (streams[0]["width"], streams[0]["height"]) != (1080, 1920)
            or Fraction(streams[0]["avg_frame_rate"]) != 24
            or int(streams[0]["nb_read_frames"]) != b["composition"]["frames"]):
        raise ValueError("Native renderer output does not match the frozen artifact clock")
    # Original Lemo JPEG captures carry full-range YUV. Convert the actual range
    # when needed; merely relabelling it as limited-range would damage contrast.
    # No resize, retiming, looping or new animation is performed.
    normalized = scene / "artifact.mp4"
    normalization = ["-c", "copy", "-aspect", "9:16", "-bsf:v", "h264_metadata=sample_aspect_ratio=1/1"]
    if streams[0].get("pix_fmt") == "yuvj420p" and streams[0].get("color_range") == "pc":
        normalization = ["-vf", "scale=in_range=pc:out_range=tv,setsar=1", "-c:v", "libx264",
                         "-crf", "16", "-pix_fmt", "yuv420p", "-color_range", "tv"]
    elif streams[0].get("pix_fmt") != "yuv420p":
        raise ValueError("Unsupported native video pixel format")
    subprocess.run([runtime["ffmpeg"], "-v", "error", "-i", str(native), *normalization, str(normalized)], check=True, timeout=30)
    subprocess.run([runtime["ffmpeg"], "-v", "error", "-i", str(normalized), "-f", "null", "-"], check=True, timeout=30)
    return normalized, {"status": "rendered", "dependency_id": dependency_id, "upstream_commit": commit,
        "native_entry_sha256": runtime["entry_sha256"], "native_argv": argv, "frames": b["composition"]["frames"],
        "production_evidence": workflow_reference(b), "native_log": log[-4000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--dependency-id", choices=tuple(SOURCES))
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--media-manifest", type=Path)
    parser.add_argument("--runtime")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.probe:
        check_runtime(args.project_root, args.dependency_id)
        print(json.dumps({"schema_version": 1, "dependency_id": args.dependency_id, "entrypoint": ENTRY,
            "producer_version": VERSION, "adapter_identity": {"adapter_type": "ReferenceProcessAdapter",
            "approved_executor": "reference_adapter", "primary_renderer": "HTMLCanvas"}}))
        return
    payload = args.brief.read_bytes()
    b = validate_brief(payload)
    manifest = json.loads(args.media_manifest.read_bytes())
    records = {f["media_ref"]: f for f in manifest["media"]}
    if (manifest["schema_version"] != "reference-process-media/v1"
            or manifest["brief_sha256"] != hashlib.sha256(payload).hexdigest()
            or len(records) != len(manifest["media"]) or set(records) != {f["media_ref"] for f in b["files"]}):
        raise ValueError("Frozen scene media manifest mismatch")
    with tempfile.TemporaryDirectory(prefix="upstream-scene-") as directory:
        scene = Path(directory)
        for f in b["files"]:
            record = records[f["media_ref"]]
            if type(record["fd"]) is not int or record["fd"] < 0:
                raise ValueError("Frozen scene descriptor required")
            data = Path(f"/dev/fd/{record['fd']}").read_bytes()
            if hashlib.sha256(data).hexdigest() != f["sha256"] or record["sha256"] != f["sha256"] or len(data) != record["byte_length"]:
                raise ValueError("Frozen scene file changed")
            target = scene / f["scene_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        output, receipt = run_native(b, scene, json.loads(base64.b64decode(args.runtime, validate=True)))
        with args.output.open("wb") as handle:
            handle.write(output.read_bytes())
        print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()

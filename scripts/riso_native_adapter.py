"""Fill Riso's public DATA slots; call its unchanged project/render/QA tools."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import subprocess
import sys
import tempfile
import time

if __file__ == "<stdin>":
    _bootstrap = argparse.ArgumentParser(add_help=False)
    _bootstrap.add_argument("--skill-root", required=True, type=Path)
    SKILL = _bootstrap.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from package_paths import PACKAGE_ROOT
    SKILL = PACKAGE_ROOT
sys.path.insert(0, str(SKILL / "scripts"))
from adapter_kit import sha256_file as sha
from riso_recovery import RecoveryBlocked, acquire_claim, checkpoint_path, load_checkpoint, media_identity, save_checkpoint
from riso_watchdog import CLEANUP_SECONDS, inherited_owner_fd, recover_pending, settle_browser, start_watchdog
ENTRY = "scripts/riso_native_adapter.py"
CHROME_LAUNCHER = "scripts/riso_chrome_launcher.py"
RECOVERY = "scripts/riso_recovery.py"
WATCHDOG = "scripts/riso_watchdog.py"
VERSION = "1.0.0"
DEPENDENCY_ID = "eian-riso-broll"
SOURCE_PIN = "e782ad7051f5fce1ca371523c144f4cb78ab5c40"
PROCESS_TIMEOUT = 300
WORK_TIMEOUT = PROCESS_TIMEOUT - 10
LOG_TAIL_BYTES = 16 * 1024
FAMILIES = {
    "title": "section_heading", "number": "numeric_emphasis",
    "compare": "numeric_comparison", "converge": "classification_reduction",
    "network": "collection_relationship", "focus": "option_selection",
    "steps": "process_flow", "shot": "evidence_source",
    "quote": "conclusion", "versus": "old_new_comparison",
}
# Native actions have fixed cue times. Longer copy still needs native layout QA.
MIN_SECONDS = {"title": 3, "number": 4, "compare": 4.5, "converge": 5,
               "network": 5, "focus": 5, "steps": 4.5, "shot": 4,
               "quote": 5, "versus": 6.5}




def exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("Riso " + label + ": unknown or missing fields")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def text(value, limit, *, empty=False, lines=1):
    if (type(value) is not str or (not empty and not value.strip())
            or any(ord(c) < 32 and c != "\n" for c in value)
            or any(c in value for c in "<>&\\`")):
        raise ValueError("Riso text must be plain speech-derived content")
    if value.count("[") != value.count("]") or re.search(r"\[[^\]]*\[|\][^\[]*\]", value):
        raise ValueError("Riso emphasis brackets are unbalanced")
    plain = value.replace("[", "").replace("]", "")
    if len(plain.split("\n")) > lines or any(len(s) > limit for s in plain.split("\n")):
        raise ValueError("Riso text exceeds native capacity")


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Riso integer is outside native capacity")


def validate_brief(payload):
    b = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    exact(b, ("schema_version", "source_binding", "composition", "template_request", "template", "data", "assets"), "brief")
    if type(b["schema_version"]) is not int or b["schema_version"] != 1 or b["template"] not in FAMILIES:
        raise ValueError("Unknown Riso native template/version")
    s, c, d, t = b["source_binding"], b["composition"], b["data"], b["template"]
    exact(s, ("aroll_sha256", "segment_id", "start", "end"), "source binding")
    if (not re.fullmatch(r"[a-f0-9]{64}", str(s["aroll_sha256"]))
            or not re.fullmatch(r"seg-[A-Za-z0-9_-]+", str(s["segment_id"]))
            or not finite(s["start"]) or not finite(s["end"]) or not 0 <= s["start"] < s["end"]):
        raise ValueError("Invalid Riso source clock")
    exact(c, ("id", "width", "height", "fps", "frames"), "composition")
    if (not re.fullmatch(r"[A-Za-z0-9_-]+", str(c["id"]))
            or any(type(c[k]) is not int or c[k] != v for k, v in (("width", 1080), ("height", 1920), ("fps", 24)))
            or type(c["frames"]) is not int or not MIN_SECONDS[t] * 24 <= c["frames"] <= 480
            or abs((s["end"] - s["start"]) * 24 - c["frames"]) > 1e-6):
        raise ValueError("Riso source window must fit unchanged native actions at 1080x1920@24")
    fields = {
        "title": ("flood", "index", "kicker", "title", "sub"),
        "number": ("number", "prefix", "suffix", "comma", "unit", "say"),
        "compare": ("title", "before", "after"), "converge": ("from", "to", "names"),
        "network": ("number", "comma", "unit", "say", "nodes"),
        "focus": ("title", "items", "pick", "verdict"), "steps": ("title", "steps", "key"),
        "shot": ("img", "slot", "note", "height", "caption", "source"),
        "quote": ("lead", "quote"), "versus": ("before", "after"),
    }
    exact(d, ("palette", "mast", "duration", *fields[t]), "native DATA")
    if (d["palette"] not in {"pal-blue", "pal-teal", "pal-red", "pal-ink"}
            or not finite(d["duration"]) or abs(d["duration"] * 24 - c["frames"]) > 1e-6
            or type(d["mast"]) is not list or len(d["mast"]) != 2):
        raise ValueError("Invalid Riso public palette/header/duration")
    for item in d["mast"]:
        text(item, 18, empty=True)
    units, numbers = 1, []
    if t == "title":
        # The native index is textContent, not a counter; its bundled font covers short Latin labels.
        if type(d["flood"]) is not bool or not re.fullmatch(r"[A-Za-z0-9]{1,2}", str(d["index"])):
            raise ValueError("Invalid Riso title index/background")
        text(d["kicker"], 6, empty=True); text(d["title"], 6, lines=2); text(d["sub"], 14, empty=True)
    elif t in {"number", "network"}:
        integer(d["number"], 0, 99999999)
        if type(d["comma"]) is not bool:
            raise ValueError("Riso comma must be boolean")
        text(d["unit"], 4); text(d["say"], 8 if t == "number" else 10, lines=2 if t == "number" else 1)
        if t == "number":
            text(d["prefix"], 2, empty=True); text(d["suffix"], 2, empty=True)
        else:
            integer(d["nodes"], 3, 80)
        numbers = [d["number"]]
    elif t == "compare":
        text(d["title"], 8)
        for side in (d["before"], d["after"]):
            exact(side, ("label", "value", "unit", "base"), "comparison side")
            text(side["label"], 6); text(side["unit"], 4)
            integer(side["value"], 0, 99999999)
            if not finite(side["base"]) or side["base"] < 0:
                raise ValueError("Riso comparison requires nonnegative common-unit values")
        a, z = d["before"], d["after"]
        if max(a["base"], z["base"]) == 0:
            raise ValueError("Riso comparison has no visible scale")
        if any((x["value"] == 0) != (x["base"] == 0) for x in (a, z)):
            raise ValueError("Riso common-unit scale contradicts displayed values")
        if a["unit"] == z["unit"] and a["value"] and z["value"] and not math.isclose(a["base"] / a["value"], z["base"] / z["value"], rel_tol=1e-9):
            raise ValueError("Riso equal units require equal scale conversions")
        units, numbers = 2, [a["value"], z["value"]]
    elif t == "converge":
        for key, low, high in (("from", 1, 36), ("to", 2, 6)):
            exact(d[key], ("n", "cap", "count"), "convergence side")
            text(d[key]["n"], 4); text(d[key]["cap"], 8); integer(d[key]["count"], low, high)
        if type(d["names"]) is not list or len(d["names"]) not in {0, d["to"]["count"]}:
            raise ValueError("Riso category labels differ from destination count")
        for item in d["names"]:
            text(item, 5)
        units = 2
    elif t == "focus":
        text(d["title"], 8)
        if type(d["items"]) is not list or not 2 <= len(d["items"]) <= 5:
            raise ValueError("Riso focus requires 2-5 native options")
        for item in d["items"]:
            text(item, 7)
        integer(d["pick"], 0, len(d["items"]) - 1)
        if d["verdict"] is not None:
            exact(d["verdict"], ("n", "text"), "focus verdict")
            text(d["verdict"]["n"], 6, empty=True); text(d["verdict"]["text"], 10)
        units = len(d["items"])
    elif t == "steps":
        if type(d["steps"]) is not list or not 2 <= len(d["steps"]) <= 6:
            raise ValueError("Riso steps requires 2-6 actions")
        for item in d["steps"]:
            text(item, 5)
        if type(d["title"]) is not list or len(d["title"]) != 3 or type(d["title"][1]) is not int or d["title"][1] != len(d["steps"]):
            raise ValueError("Riso step title must state its actual step count")
        text(d["title"][0], 4, empty=True); text(d["title"][2], 4, empty=True)
        integer(d["key"], -1, len(d["steps"]) - 1)
        units, numbers = len(d["steps"]), [len(d["steps"])]
    elif t == "quote":
        text(d["lead"], 16, empty=True); text(d["quote"], 7, lines=4)
        if len(d["quote"].split("\n")) < 2:
            raise ValueError("Riso quote needs 2-4 readable lines")
    elif t == "versus":
        for side in (d["before"], d["after"]):
            exact(side, ("tag", "text"), "versus side")
            text(side["tag"], 4); text(side["text"], 8, lines=2)
        units = 2
    elif t == "shot":
        text(d["slot"], 10); text(d["caption"], 10); text(d["source"], 20, empty=True)
        integer(d["height"], 240, 780)
        if d["note"] is not None:
            exact(d["note"], ("x", "y", "w", "h"), "screenshot annotation")
            n = d["note"]
            if any(not finite(n[k]) or not 0 <= n[k] <= 1 for k in n) or not n["w"] or not n["h"] or n["x"] + n["w"] > 1 or n["y"] + n["h"] > 1:
                raise ValueError("Riso annotation must stay within the actual screenshot")
    if type(b["assets"]) is not list or len(b["assets"]) != (1 if t == "shot" else 0):
        raise ValueError("Riso shot needs one real screenshot; other templates accept no media")
    if t == "shot":
        a = b["assets"][0]
        exact(a, ("media_ref", "job_path", "scene_path", "sha256"), "screenshot")
        p = Path(a["job_path"])
        if (a["media_ref"] != "shot" or p.is_absolute() or ".." in p.parts or p.as_posix() != a["job_path"]
                or not re.fullmatch(r"assets/shots/shot\.(png|jpg|webp)", str(a["scene_path"]))
                or d["img"] != "../" + a["scene_path"] or not re.fullmatch(r"[a-f0-9]{64}", str(a["sha256"]))):
            raise ValueError("Riso screenshot must be a frozen local input, not a placeholder or URL")
    expected_request = {"semantic_family": FAMILIES[t], "information_units": units,
                        "numeric_values": numbers, "numeric_scale": "linear" if numbers else "not_applicable"}
    request = b["template_request"]
    exact(request, expected_request, "template request")
    if (type(request["information_units"]) is not int
            or type(request["numeric_values"]) is not list
            or any(not finite(v) for v in request["numeric_values"])
            or request != expected_request):
        raise ValueError("Riso template request contradicts native visible content")
    return b


def check_runtime(project_root, executables=None):
    project = Path(project_root).resolve(strict=True)
    source = project / "vendor/eian-riso-broll"
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Riso source must be the project-local upstream checkout")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True, timeout=5).strip() != SOURCE_PIN:
        raise ValueError("Riso source revision changed; review before updating the connection")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True, timeout=5).strip():
        raise ValueError("Riso source is modified; no source repair or fallback")
    paths = {k: str(Path((executables or {}).get(k) or shutil.which(k) or "missing").resolve(strict=True))
             for k in ("node", "ffmpeg", "ffprobe")}
    browser = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not browser.is_file() or not os.access(browser, os.X_OK):
        raise ValueError("Riso needs the existing system Chrome; no browser installation")
    crashpad = (browser.parent.parent / "Frameworks/Google Chrome Framework.framework/Versions/Current"
                / "Helpers/chrome_crashpad_handler").resolve(strict=True)
    paths.update(source=str(source), browser=str(browser), crashpad=str(crashpad))
    version = subprocess.check_output([paths["node"], "--version"], text=True, timeout=5).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise ValueError("Riso requires existing Node >=22")
    paths["chrome_launcher_sha256"] = sha(SKILL / CHROME_LAUNCHER)
    paths["implementation_identity"] = hashlib.sha256(
        (paths["chrome_launcher_sha256"] + sha(SKILL / RECOVERY) + sha(SKILL / WATCHDOG)).encode()
    ).hexdigest()
    hashes = [sha(paths[k]) for k in ("node", "ffmpeg", "ffprobe", "browser", "crashpad")]
    paths["identity"] = hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    return paths


def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    python = Path(python_executable).resolve(strict=True)
    runtime, entry_sha = check_runtime(project), sha(SKILL / ENTRY)

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        if (recipe.get("composition", {}).get("family") not in {"single_full_frame", "evidence_with_data_overlay"}
                or component.get("layer_role") != "base"
                or component.get("render_window", {}).get("layout_slot") != "full_frame"):
            raise ValueError("Riso requires opaque full-frame B-roll, not an A-roll overlay")
        if sha(SKILL / ENTRY) != entry_sha or check_runtime(project) != runtime:
            raise ValueError("Bound Riso adapter/runtime changed")
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(x for x in plan["segments"] if x["segment_id"] == recipe["segment_id"])
        expected = {"aroll_sha256": plan["edited_aroll_sha256"], "segment_id": segment["segment_id"], "start": segment["start"], "end": segment["end"]}
        if (json.loads(json.dumps(recipe)) != segment["shot_recipe"] or b["source_binding"] != expected
                or b["template_request"] != json.loads(json.dumps(component["invocation_record"]["template_request"]))
                or component.get("template_id") != DEPENDENCY_ID + "/" + b["template"]
                or component.get("source_sha256") != entry_sha
                or component.get("artifact_contract") != {"width": 1080, "height": 1920, "fps": 24, "alpha": False}
                or component["render_window"].get("start_frame") != 0
                or component["render_window"].get("end_frame") != b["composition"]["frames"]):
            raise ValueError("Riso no longer matches the approved opaque shot")
        return payload

    def media(job, recipe, component, payload):
        return tuple(ReferenceProcessMedia(media_ref=a["media_ref"], job_path=a["job_path"], sha256=a["sha256"])
                     for a in validate_brief(payload)["assets"])

    return ReferenceProcessAdapter(
        adapter_id="riso-native-data-v1", dependency_id=DEPENDENCY_ID, approved_executor="reference_adapter",
        dependency_root=SKILL, entrypoint=ENTRY, entrypoint_sha256=entry_sha, producer_version=VERSION,
        primary_renderer="HTMLCanvas", renderer_version=VERSION, artifact_media_type="video",
        launcher=python, launcher_sha256=sha(python), brief_loader=guard, media_loader=media,
        self_contained_wrapper=True, timeout_seconds=PROCESS_TIMEOUT,
        argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--media-manifest", "{media_manifest_fd}",
                       "--skill-root", str(SKILL), "--project-root", str(project), "--node", runtime["node"],
                       "--ffmpeg", runtime["ffmpeg"], "--ffprobe", runtime["ffprobe"], "--runtime-identity", runtime["identity"],
                       "--implementation-identity", runtime["implementation_identity"],
                       "--output", "{output_path}"))


def create_binding(adapter, payload, reference_sample):
    b = validate_brief(payload)
    if adapter.dependency_id != DEPENDENCY_ID or adapter.entrypoint_sha256 != sha(SKILL / ENTRY):
        raise ValueError("Riso adapter identity changed")
    digest = hashlib.sha256(payload).hexdigest()
    r = b["template_request"]
    return {"producer_type": "dependency", "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY,
            "producer_version": VERSION, "primary_renderer": "HTMLCanvas", "renderer_version": VERSION,
            "template_origin": "custom_fallback", "template_id": DEPENDENCY_ID + "/" + b["template"],
            "template_version": VERSION, "adaptation_level": "structural", "source_entrypoint": ENTRY,
            "source_sha256": adapter.entrypoint_sha256, "sample_sha256": sha(reference_sample),
            "semantic_families": [r["semantic_family"]],
            "capacity": {"min_units": r["information_units"], "max_units": r["information_units"]},
            "brief_sha256": digest, "verification_id": hashlib.sha256((adapter.entrypoint_sha256 + digest).encode()).hexdigest(),
            "invocation_record": {"argv": [str(adapter.launcher), ENTRY], "status": "planned", "exit_code": None, "template_request": r}}


def create_artifact_probe(ffprobe_executable):
    from whiteboard_adapter import create_artifact_probe as opaque_probe
    return opaque_probe(ffprobe_executable)


def chrome_environment(work, runtime):
    source = (SKILL / CHROME_LAUNCHER).read_bytes()
    if hashlib.sha256(source).hexdigest() != runtime["chrome_launcher_sha256"]:
        raise ValueError("Bound Riso Chrome launcher changed")
    relay = work / "chrome_launcher.py"
    relay.write_bytes(source)
    shim = work / "chrome"
    shim.write_text('#!/bin/sh\nexec "$RISO_CHROME_PYTHON" "$RISO_CHROME_RELAY" "$@"\n', encoding="utf-8")
    shim.chmod(0o700)
    profiles = work / "chrome-profiles"
    profiles.mkdir(mode=0o700)
    return {
        "CHROME": str(shim),
        "RISO_CHROME_PYTHON": sys.executable,
        "RISO_CHROME_RELAY": str(relay),
        "RISO_CHROME_BINARY": runtime["browser"],
        "TMPDIR": str(profiles),
    }


def log_tail(log):
    fd = log.fileno()
    start = max(0, os.fstat(fd).st_size - LOG_TAIL_BYTES)
    return os.pread(fd, LOG_TAIL_BYTES, start).decode("utf-8", "replace")


def wait_for_command(process, deadline, owner_fd, watchdog):
    while True:
        if owner_fd is not None and select.select([owner_fd], [], [], 0)[0]:
            raise RecoveryBlocked("Riso 的父执行器已退出，本次停止并保留已验证结果。")
        if watchdog is not None and watchdog.process.poll() is not None:
            raise RecoveryBlocked("Riso 的浏览器监护异常退出，本次已停止，等待核对遗留进程。")
        remaining = deadline - time.monotonic()
        try:
            return process.wait(timeout=max(0, min(remaining, 0.1)))
        except subprocess.TimeoutExpired:
            if remaining <= 0:
                raise


def native_frame_count(duration):
    # Match Math.round of the binary64 product, including values just below a half.
    product = duration * 30
    whole = math.floor(product)
    return whole + (product - whole >= 0.5)


def probe_native(runtime, native, duration, run):
    raw = json.loads(run([runtime["ffprobe"], "-v", "error", "-err_detect", "explode", "-count_frames",
                          "-show_streams", "-of", "json", str(native)], quiet=True))["streams"]
    if (len(raw) != 1 or raw[0].get("codec_type") != "video"
            or raw[0].get("avg_frame_rate") != "30/1"
            or (raw[0].get("width"), raw[0].get("height")) != (1080, 1920)
            or int(raw[0].get("nb_read_frames", 0)) != native_frame_count(duration)):
        raise ValueError("Native Riso output changed; stop before normalization")
    source = raw[0]
    if source.get("color_range") == "pc" or source.get("pix_fmt", "").startswith("yuvj"):
        input_range = "full"
    elif source.get("color_range") == "tv":
        input_range = "limited"
    else:
        raise ValueError("Native Riso color range is unknown")
    return input_range


def normalize_output(runtime, native, target, frames, input_range, run):
    """Export unchanged native motion at the parent's clock and color range."""
    # Convert pixel values, not just their metadata. JPEG captures use full range.
    # MP4's default millisecond movie clock rounds edit lists between 24fps ticks.
    run([runtime["ffmpeg"], "-n", "-v", "error", "-xerror", "-i", str(native), "-map", "0:v:0", "-an",
         "-vf", f"fps=24,scale=in_range={input_range}:out_range=limited,setsar=1",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-color_range", "tv",
         "-frames:v", str(frames), "-movie_timescale", "24000", "-movflags", "+faststart", str(target)])
    streams = json.loads(run([runtime["ffprobe"], "-v", "error", "-show_streams", "-of", "json", str(target)]))["streams"]
    if len(streams) != 1:
        raise ValueError("Riso export must contain one silent video stream")
    v = streams[0]
    if ((v["width"], v["height"], v["avg_frame_rate"], v["sample_aspect_ratio"], int(v["nb_frames"]), v["pix_fmt"], v.get("color_range"))
            != (1080, 1920, "24/1", "1:1", frames, "yuv420p", "tv")
            or abs(float(v["duration"]) - frames / 24) > 1e-5):
        raise ValueError("Riso export changed the output clock or color format")
    return {"frames": frames, "input_range": input_range, "pixel_format": v["pix_fmt"], "color_range": v["color_range"]}


def render(args):
    deadline = time.monotonic() + WORK_TIMEOUT
    # Read each inherited descriptor once; later checks reuse these exact bytes.
    payload = Path(args.brief).read_bytes()
    b = validate_brief(payload)
    runtime = check_runtime(args.project_root, {k: getattr(args, k) for k in ("node", "ffmpeg", "ffprobe")})
    if runtime["identity"] != args.runtime_identity or runtime["implementation_identity"] != args.implementation_identity:
        raise ValueError("Bound Riso executables changed")
    brief_sha = hashlib.sha256(payload).hexdigest()
    frozen = json.loads(Path(args.media_manifest).read_bytes())
    if frozen.get("schema_version") != "reference-process-media/v1" or frozen.get("brief_sha256") != brief_sha:
        raise ValueError("Riso frozen input differs from the bound brief")
    records = {a["media_ref"]: a for a in frozen["media"]}
    if len(records) != len(frozen["media"]) or set(records) != {a["media_ref"] for a in b["assets"]}:
        raise ValueError("Wrong Riso screenshot set")
    assets = {}
    for asset in b["assets"]:
        record = records[asset["media_ref"]]
        blob = Path("/dev/fd/" + str(record["fd"])).read_bytes()
        if (record["sha256"] != asset["sha256"] or len(blob) != record["byte_length"]
                or hashlib.sha256(blob).hexdigest() != asset["sha256"]):
            raise ValueError("Riso frozen screenshot changed")
        assets[asset["scene_path"]] = blob
    invocation_id = os.environ.get("BROLL_INVOCATION_ID") or f"process-{secrets.token_hex(16)}"
    if not re.fullmatch(r"process-[0-9a-f]{32}", invocation_id):
        raise ValueError("Invalid Riso invocation identity")
    parent = (Path(args.project_root) / "runtime/riso-renders").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="native-", dir=parent))
    input_sha = os.environ.get("BROLL_COMPONENT_INPUT_SHA256")
    job_dir = os.environ.get("BROLL_JOB_DIR")
    checkpoint = checkpoint_path(parent, input_sha, job_dir, runtime, brief_sha, sha(SKILL / ENTRY))
    owner_fd = inherited_owner_fd(os.environ.get("BROLL_OWNER_LIFETIME_FD"))
    claim_fd = None
    watchdog = None
    expected_native_frames = native_frame_count(b["data"]["duration"])
    report = {"status": "preparing", "template": b["template"], "source_pin": SOURCE_PIN,
              "invocation_id": invocation_id, "brief_sha256": brief_sha, "commands": [],
              "native_fps": 30, "output_fps": 24, "time_scale": 1, "external_requests": 0}

    def run(argv, *, browser_phase=None, quiet=False):
        record = {"argv": argv, "exit_code": None, "stdout": "", "stderr": ""}
        report["commands"].append(record)
        started = time.monotonic()
        if started >= deadline:
            record["timed_out"] = True
            raise TimeoutError("Riso reached its total execution deadline")
        command_env = dict(environment)
        command = argv
        chrome_log = None
        if watchdog is not None:
            command = [sys.executable, chrome_env["RISO_CHROME_RELAY"], "--guard-command", *argv]
            command_env.update(
                RISO_WATCHDOG_SOCKET=str(watchdog.socket_path),
                RISO_WATCHDOG_COMMAND=f"{browser_phase}-command" if browser_phase else f"command-{len(report['commands'])}",
                RISO_WORK_DEADLINE=str(deadline),
            )
        if browser_phase:
            chrome_log = work / (browser_phase + ".chrome.log")
            record["browser_log"] = chrome_log.name
            command_env.update(chrome_env, RISO_CHROME_LOG=str(chrome_log),
                               RISO_WATCHDOG_PHASE=f"{browser_phase}-browser")
        stdout_path = work / f"command-{len(report['commands'])}.stdout.log"
        stderr_path = work / f"command-{len(report['commands'])}.stderr.log"
        with stdout_path.open("w+b") as stdout, stderr_path.open("w+b") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=command_env)
            try:
                wait_for_command(process, deadline, owner_fd, watchdog)
            except (subprocess.TimeoutExpired, RecoveryBlocked) as error:
                record["timed_out"] = isinstance(error, subprocess.TimeoutExpired)
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                    record["cleanup_error"] = str(cleanup_error)
                raise
            finally:
                record.update(exit_code=process.returncode, elapsed_seconds=round(time.monotonic() - started, 3),
                              stdout=log_tail(stdout), stderr=log_tail(stderr))
                if browser_phase:
                    try:
                        record["settled_crashpad_pids"] = settle_browser(work, browser_phase, runtime,
                                                                        time.monotonic() + CLEANUP_SECONDS)
                    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as cleanup_error:
                        record["browser_cleanup_error"] = str(cleanup_error)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, argv, record["stdout"], record["stderr"])
        if "browser_cleanup_error" in record:
            raise RuntimeError(record["browser_cleanup_error"])
        if quiet and record["stderr"]:
            raise ValueError("Native Riso output contains decoder errors")
        return record["stdout"]

    environment = dict(os.environ)
    try:
        claim_fd, pending = acquire_claim(parent, input_sha, job_dir, min(deadline, time.monotonic() + CLEANUP_SECONDS))
        recover_pending(pending, parent, min(deadline, time.monotonic() + CLEANUP_SECONDS))
        recovered = load_checkpoint(checkpoint, parent, b["composition"]["id"], expected_native_frames)
        if recovered is not None:
            native, source = recovered
            report.update(native_source=source, native_reused=True)
        else:
            chrome_env = chrome_environment(work, runtime)
            watchdog = start_watchdog(work, runtime, invocation_id, pending, owner_fd, claim_fd)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            environment["PATH"] = os.pathsep.join((str(bin_dir), "/usr/bin", "/bin"))
            for tool in ("ffmpeg", "ffprobe"):
                shim = bin_dir / tool
                variable = "RISO_" + tool.upper()
                shim.write_text(f'#!/bin/sh\nexec "$RISO_CHROME_PYTHON" "$RISO_CHROME_RELAY" --guard-tool {tool} "$@"\n')
                shim.chmod(0o700)
                environment[variable] = runtime[tool]
            # Upstream explicitly permits replacing only DATA in a project copy.
            prepare = r"""
import {createProject, addTemplate} from './scripts/lib/project.mjs';
import {readFileSync, writeFileSync} from 'node:fs';
const [dir, template, id, input] = process.argv.slice(1);
createProject(dir); const file = addTemplate(dir, template, id);
const html = readFileSync(file, 'utf8');
const expression = /const DATA = \{[\s\S]*?\n\};/g;
if ([...html.matchAll(expression)].length !== 1) throw Error('Native DATA boundary changed');
const data = JSON.parse(readFileSync(input, 'utf8'));
writeFileSync(file, html.replace(expression, () => 'const DATA = ' + JSON.stringify(data) + ';'));
"""
            data_file = work / "data.json"
            data_file.write_text(json.dumps(b["data"], ensure_ascii=False), encoding="utf-8")
            # The module import is resolved against the unmodified source, not cwd.
            prepare = prepare.replace("'./scripts/lib/project.mjs'", json.dumps((Path(runtime["source"]) / "scripts/lib/project.mjs").as_uri()))
            native_project = work / "project"
            run([runtime["node"], "--input-type=module", "-e", prepare, str(native_project), b["template"], b["composition"]["id"], str(data_file)])
            for path, blob in assets.items():
                (native_project / path).write_bytes(blob)
            composition = native_project / "compositions" / (b["composition"]["id"] + ".html")
            run([runtime["node"], str(Path(runtime["source"]) / "scripts/qa.mjs"), str(composition)], browser_phase="qa")
            native = native_project / "renders" / (b["composition"]["id"] + ".mp4")
            run([runtime["node"], str(Path(runtime["source"]) / "scripts/render.mjs"), str(composition), "-o", str(native)],
                browser_phase="render")
            input_range = probe_native(runtime, native, b["data"]["duration"], run)
            digest, byte_count = media_identity(native, durable=checkpoint is not None)
            source = {"invocation_id": invocation_id, "sha256": digest, "bytes": byte_count,
                      "frames": expected_native_frames, "input_range": input_range}
            save_checkpoint(checkpoint, work, source)
            report.update(native_source=source, native_reused=False)
        target = work / "output.mp4"
        exported = normalize_output(runtime, native, target, b["composition"]["frames"], source["input_range"], run)
        if media_identity(native) != (source["sha256"], source["bytes"]):
            raise ValueError("Riso native source changed during normalization")
        if watchdog is not None:
            active, watchdog = watchdog, None
            active.finish()
        # Native input/source files and timestamps remain unchanged. No interpolation.
        shutil.copyfile(target, args.output)
        report.update(status="completed", output_sha256=sha(target), output_frames=exported["frames"],
                      color_conversion=exported, normalization="timestamp sampling 30->24; duration and speed unchanged; SAR=1:1; actual range conversion to limited yuv420p")
    except Exception as error:
        report.update(status="failed", error=str(error), error_type=type(error).__name__)
        raise RuntimeError("Riso stopped without retry; inspect " + str(work / "invocation.json")) from error
    finally:
        if watchdog is not None:
            try:
                watchdog.finish()
            except RecoveryBlocked as error:
                report["watchdog_cleanup_error"] = str(error)
        for descriptor in (claim_fd, owner_fd):
            if descriptor is not None:
                os.close(descriptor)
        (work / "invocation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**report, "evidence_path": str(work / "invocation.json")}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", required=True)
    p.add_argument("--skill-root", default=SKILL, type=Path)
    p.add_argument("--probe", action="store_true")
    for name in ("brief", "media-manifest", "node", "ffmpeg", "ffprobe", "runtime-identity", "implementation-identity", "output"):
        p.add_argument("--" + name)
    args = p.parse_args()
    if args.probe:
        check_runtime(args.project_root)
        print(json.dumps({"schema_version": 1, "dependency_id": DEPENDENCY_ID, "entrypoint": ENTRY, "producer_version": VERSION,
                          "adapter_identity": {"adapter_type": "ReferenceProcessAdapter", "approved_executor": "reference_adapter", "primary_renderer": "HTMLCanvas"}}))
    else:
        missing = [name for name in ("brief", "media-manifest", "node", "ffmpeg", "ffprobe", "runtime-identity", "implementation-identity", "output") if getattr(args, name.replace("-", "_")) is None]
        if missing:
            p.error("render mode requires --" + " --".join(missing))
        try:
            print(json.dumps(render(args), ensure_ascii=False))
        except RuntimeError as error:
            if isinstance(error.__cause__, RecoveryBlocked):
                print("Riso recovery diagnostic: " + str(error.__cause__), file=sys.stderr)
            raise

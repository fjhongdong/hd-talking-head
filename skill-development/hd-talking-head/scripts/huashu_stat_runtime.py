"""Check project tools for native stat export or explicit MOV reuse; never install."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from adapter_kit import identity_from_digests, sha256_file as sha

SOURCE_PIN = "5f2608c2e12abcf518f74dde86093b19f7f88603"
SYSTEM_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SOURCE_FILES = (
    "package.json", "cli/om.js", "cli/lib/project.js", "cli/lib/render.js",
    "cli/lib/render-om.js", "cli/lib/browser.js", "runtime/om.js",
    "templates/talking-head/index.html", "templates/talking-head/template.json",
    "templates/blank/vendor/gsap.min.js", "fonts/NotoSansSC-500.woff",
    "fonts/NotoSansSC-900.woff", "fonts/Inter-var.woff",
)


def _run(argv, *, cwd=None, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          check=True, timeout=30)

def check_runtime(project_root, tools=None, *, mode="native_export"):
    if mode not in {"native_export", "reuse_mov"}:
        raise ValueError("Choose native_export or reuse_mov explicitly")
    project = Path(project_root).resolve(strict=True)
    vendor = project / "skill-development/vendor/huashu-motion"
    names = ("ffmpeg", "ffprobe") if mode == "reuse_mov" else ("node", "ffmpeg", "ffprobe", "chrome")
    found = {}
    for name in names:
        raw = (tools or {}).get(name) or (SYSTEM_CHROME if name == "chrome" else shutil.which(name))
        if not raw:
            raise ValueError("Huashu stat tool missing: " + name)
        path = Path(raw).resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Huashu stat tool not executable: " + name)
        found[name] = str(path)
    filters = _run([found["ffmpeg"], "-hide_banner", "-filters"]).stdout
    available = {p[1] for line in filters.splitlines() if len(p := line.split()) >= 3}
    required = {"fps", "setpts", "setsar", "format", "scale", "crop", "pad", "overlay", "alphaextract"}
    if not required <= available:
        raise ValueError("Huashu stat FFmpeg filters missing: " + ", ".join(sorted(required - available)))
    encoders = _run([found["ffmpeg"], "-hide_banner", "-encoders"]).stdout
    available = {p[1] for line in encoders.splitlines() if len(p := line.split()) >= 3}
    if "qtrle" not in available:
        raise ValueError("Huashu stat requires the existing qtrle encoder")
    _run([found["ffprobe"], "-version"])
    files = [Path(__file__), *(Path(p) for p in found.values())]
    versions = {}
    if mode == "native_export":
        revision = _run(["/usr/bin/git", "rev-parse", "--show-toplevel", "HEAD"], cwd=vendor).stdout.splitlines()
        if revision != [str(vendor), SOURCE_PIN]:
            raise ValueError("Huashu Motion source root or revision changed")
        if _run(["/usr/bin/git", "status", "--porcelain"], cwd=vendor).stdout.strip():
            raise ValueError("Huashu Motion source is modified; stopped without repair")
        files += [vendor / name for name in SOURCE_FILES]
        versions["node_version"] = _run([found["node"], "--version"]).stdout.strip()
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", versions["node_version"])
        if not match or int(match[1]) < 22:
            raise ValueError("Huashu Motion requires Node >= 22")
        versions["chrome_version"] = _run([found["chrome"], "--version"]).stdout.strip()
    identity = identity_from_digests(files, header_lines=(mode, SOURCE_PIN))
    return dict(found, mode=mode, root=str(vendor), vendor=str(vendor), identity=identity,
                source_revision=SOURCE_PIN, **versions)

def probe_runtime(project_root, runtime=None):
    info = runtime or check_runtime(project_root)
    if info["mode"] == "native_export":
        _run([info["node"], str(Path(info["vendor"]) / "cli/om.js"), "--help"])
        script = ("import {findChrome} from " + json.dumps((Path(info["vendor"]) / "cli/lib/browser.js").as_uri()) +
                  ";if(findChrome()!==process.env.OM_CHROME)throw new Error('browser identity differs');")
        env = {k:v for k,v in os.environ.items() if k in {"HOME", "TMPDIR", "LANG", "PATH"}}
        env["OM_CHROME"] = info["chrome"]
        _run([info["node"], "--input-type=module", "-e", script], env=env)
    return dict(identity=info["identity"], status="callable", mode=info["mode"],
                boundary="existing tools and native CLI; no media generated")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--mode", choices=("native_export", "reuse_mov"), default="native_export")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    runtime = check_runtime(args.project_root, mode=args.mode)
    print(json.dumps(probe_runtime(args.project_root, runtime) if args.probe else runtime))

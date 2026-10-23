"""Check the existing project runtime; never install or update dependencies."""
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

SOURCE_PIN = "e35e1aff9dae3b3addc21f68f3bcd51f95bdc1a8"
SYSTEM_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"




def check_runtime(project_root, tools=None):
    project = Path(project_root).resolve(strict=True)
    vendor = project / "skill-development/vendor/overlay-studio"
    runtime = project / "skill-development/runtime/overlay-studio-e35e1aff"
    result = subprocess.run(["/usr/bin/git", "rev-parse", "--show-toplevel", "HEAD"],
                            cwd=vendor, capture_output=True, text=True, check=True, timeout=15)
    if result.stdout.splitlines() != [str(vendor), SOURCE_PIN]:
        raise ValueError("Overlay Studio source revision or repository root changed")
    result = subprocess.run(["/usr/bin/git", "status", "--porcelain"], cwd=vendor,
                            capture_output=True, text=True, check=True, timeout=15)
    if result.stdout.strip():
        raise ValueError("Overlay Studio source is modified; stopped without repair")
    for name in ("package.json", "package-lock.json"):
        if sha(runtime / name) != sha(vendor / "motion-playground" / name):
            raise ValueError("Overlay Studio runtime lock differs from native source")
    executables = {}
    for name in ("node", "ffmpeg", "ffprobe", "chrome"):
        raw = (tools or {}).get(name) or (SYSTEM_CHROME if name == "chrome" else shutil.which(name))
        if not raw:
            raise ValueError("Overlay Studio tool missing: " + name)
        path = Path(raw).resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Overlay Studio tool not executable: " + name)
        executables[name] = str(path)
    node = subprocess.run([executables["node"], "--version"], capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", node)
    if not match or tuple(map(int, match.groups())) < (22, 12, 0):
        raise ValueError("Overlay Studio requires Node >= 22.12 in this runtime")
    chrome = subprocess.run([executables["chrome"], "--version"], capture_output=True,
                            text=True, check=True, timeout=15).stdout.strip()
    files = [runtime / "package.json", runtime / "package-lock.json", Path(__file__),
             *(Path(p) for p in executables.values())]
    files += [vendor / p for p in (
        ".agents/skills/overlay-fx-generator/SKILL.md",
        "motion-playground/scripts/export-frames.mjs",
        "motion-playground/src/effects/hud/PinBoardPlate.tsx")]
    identity = identity_from_digests(files)
    return dict(executables, root=str(runtime), vendor=str(vendor), identity=identity,
                node_version=node, chrome_version=chrome, source_revision=SOURCE_PIN)


def probe_runtime(project_root, runtime=None):
    info = runtime or check_runtime(project_root)
    # Actual module load and selected-browser launch. No scene, external page,
    # generation service or media is opened.
    script = """const {createRequire}=require('node:module');
const {pathToFileURL}=require('node:url');
const req=createRequire(process.argv[1]);
(async()=>{await import(pathToFileURL(req.resolve('vite')).href);req('react');
 const puppeteer=req('puppeteer');
 const browser=await puppeteer.launch({executablePath:process.argv[2],headless:true});
 try{console.log(JSON.stringify({browser:await browser.version(),modules:'loaded'}));}
 finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});"""
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}}
    environment.update(PUPPETEER_SKIP_DOWNLOAD="true", BROWSER="none")
    result = subprocess.run([info["node"], "-e", script,
                             str(Path(info["root"]) / "package.json"), info["chrome"]],
                            capture_output=True, text=True, check=True, timeout=35, env=environment)
    return dict(identity=info["identity"], status="callable", **json.loads(result.stdout))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    # Check existing files; the registered adapter probe launches the browser.
    print(json.dumps(check_runtime(args.project_root), ensure_ascii=False))


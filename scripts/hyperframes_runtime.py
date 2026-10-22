"""Resolve the pinned published HyperFrames runtime used by all local adapters."""
from pathlib import Path
import json
import subprocess
import shutil
import argparse
import hashlib

VERSION = "0.8.167"
PACKAGE = "hyperframes"

def resolve_tools(node=None, ffmpeg=None, ffprobe=None):
    paths = {"node": node or shutil.which("node"), "ffmpeg": ffmpeg or shutil.which("ffmpeg"), "ffprobe": ffprobe or shutil.which("ffprobe")}
    if any(not value for value in paths.values()):
        raise ValueError("node, ffmpeg and ffprobe are required")
    result = {key: Path(value).resolve(strict=True) for key, value in paths.items()}
    return result, {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in result.items()}

def resolve_runtime(root):
    runtime = Path(root).resolve(strict=True)
    package = runtime / "node_modules" / PACKAGE / "package.json"
    data = json.loads(package.read_text())
    if data.get("name") != PACKAGE or data.get("version") != VERSION:
        raise ValueError("runtime_root is not hyperframes@0.8.167")
    cli = runtime / "node_modules" / PACKAGE / "bin" / "hyperframes.mjs"
    if not cli.is_file():
        raise ValueError("published HyperFrames CLI is missing")
    return {"root": runtime, "package": package, "cli": cli, "version": VERSION}

def prepare_runtime(project_root):
    """Install the exact published runtime from the checked-in package lock."""
    project = Path(project_root).resolve(strict=True)
    if not (project / "edit/hd/tools/state.py").is_file():
        raise ValueError("not a talking-head project root")
    skill = Path(__file__).resolve().parents[1]
    source = skill / "assets" / "hyperframes-runtime"
    target = project / "skill-development" / "runtime" / "hyperframes-0.8.167"
    if not (source / "package.json").is_file() or not (source / "package-lock.json").is_file():
        raise ValueError("hyperframes runtime package resources are missing")
    if target.is_symlink() or target.resolve() != target.absolute() or not target.resolve().is_relative_to(project):
        raise ValueError("HyperFrames runtime must stay inside the project")
    target.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        dst = target / name
        if dst.exists() and dst.read_bytes() != (source / name).read_bytes():
            raise ValueError("Existing HyperFrames dependency configuration differs")
        if not dst.exists():
            shutil.copyfile(source / name, dst)
    if not (target / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs").is_file():
        subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=target, check=True, timeout=240)
    return resolve_runtime(target)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.prepare:
        parser.error("use --prepare")
    print(json.dumps({"version": prepare_runtime(args.project_root)["version"]}))

#!/usr/bin/env python3
"""Run the portable hd-talking-head Skill from its package root."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

_path_module = Path(__file__).resolve().parent / "scripts/package_paths.py"
if not _path_module.is_file():
    print("Skill 包不完整，缺少启动文件：scripts/package_paths.py；已停止，请恢复同版本完整包。",
          file=sys.stderr)
    raise SystemExit(2)

from scripts.package_paths import PACKAGE_ROOT, SCRIPTS

COMMANDS = {
    "initialize_video_job": "initialize_video_job.py",
    "verify": "verify_skill_release.py",
    "preflight": "dependency_preflight.py",
    "prepare": "project_python.py",
    "run_stage": "run_stage.py",
    "run_generation": "run_generation.py",
    "confirm_job_setup": "confirm_job_setup.py",
    "migrate_job_context": "migrate_job_context.py",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = args.arguments
    script = SCRIPTS / COMMANDS[args.command]
    required = {script}
    if args.command != "verify":
        required.add(SCRIPTS / "project_python.py")
    missing = sorted(path for path in required if not path.is_file())
    if missing:
        print("Skill 包不完整，缺少启动文件："
              + "、".join(str(path.relative_to(PACKAGE_ROOT)) for path in missing)
              + "；已停止，请恢复同版本完整包。", file=sys.stderr)
        return 2
    command = [sys.executable, str(SCRIPTS / "project_python.py"),
               "--project-root", str(PACKAGE_ROOT)]
    if args.command == "prepare":
        command += ["--prepare", *forwarded]
    elif args.command == "verify":
        command = [sys.executable, str(script), *forwarded]
    else:
        command += ["--", str(script), *forwarded]
    return subprocess.run(command, cwd=PACKAGE_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

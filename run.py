#!/usr/bin/env python3
"""Run the portable hd-talking-head Skill from its package root."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = PACKAGE_ROOT / "skill-development" / "hd-talking-head"
SCRIPTS = SKILL_ROOT / "scripts"

COMMANDS = {
    "initialize_video_job": "initialize_video_job.py",
    "verify": "verify_skill_release.py",
    "preflight": "dependency_preflight.py",
    "prepare": "project_python.py",
    "run_stage": "run_stage.py",
    "run_generation": "run_generation.py",
    "confirm_job_setup": "confirm_job_setup.py",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = args.arguments
    script = SCRIPTS / COMMANDS[args.command]
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

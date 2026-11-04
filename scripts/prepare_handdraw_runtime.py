"""Prepare locked ordinary packages in the shared project-local HandDraw prefix."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys

from package_paths import PACKAGE_ROOT


def _name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def missing_packages(prefix, requirements):
    locked = {}
    for line in Path(requirements).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line.strip())
        if match is None or _name(match[1]) in locked:
            raise ValueError("HandDraw requires unique exact package versions")
        locked[_name(match[1])] = match[2]
    if not locked:
        raise ValueError("HandDraw package lock is empty")
    installed = {_name(dist.metadata['Name']): dist.version
                 for dist in importlib.metadata.distributions(path=[str(prefix)])}
    changed = {name: version for name, version in installed.items()
               if name in locked and version != locked[name]}
    if changed:
        raise ValueError("Existing HandDraw package versions differ; preserve the prefix: " + json.dumps(changed))
    return [name + "==" + version for name, version in locked.items() if name not in installed]


def prepare(project=PACKAGE_ROOT):
    project = Path(project).resolve(strict=True)
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Run HandDraw preparation with the installed Python 3.12 interpreter")
    prefix = project / "runtime/handdraw-python312"
    if prefix.resolve() != prefix.absolute():
        raise ValueError("HandDraw packages must use a regular project-local prefix")
    requirements = project / "references/handdraw-python312-requirements.txt"
    missing = missing_packages(prefix, requirements)
    if missing:
        prefix.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "--no-input", "--no-deps", "--target", str(prefix), *missing],
                       check=True, timeout=300)
        if missing_packages(prefix, requirements):
            raise ValueError("HandDraw preparation did not provide every locked package")
    return {"status": "ready", "package_directory": str(prefix), "installed": missing}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=PACKAGE_ROOT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.project_root)))

"""Prepare OneTake's selected render dependencies entirely inside the package."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

PACKAGES = {"playwright": "1.61.0", "numpy": "2.5.3", "Pillow": "12.3.0",
            "scipy": "1.18.1", "matplotlib": "3.11.2", "fonttools": "4.66.1", "brotli": "1.2.0"}


def verify_source(project_root, expected_commit):
    from prepare_sources import bundled_source_revision
    project = Path(project_root).resolve(strict=True)
    source = project / "vendor/onetake"
    if source.is_symlink() or not source.is_dir():
        raise ValueError("OneTake requires its project-local source directory")
    if bundled_source_revision(project, source) != expected_commit:
        raise ValueError("OneTake original source differs from its pinned complete archive")
    return source


def runtime_details(project_root):
    project = Path(project_root).resolve(strict=True)
    environment = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(project / "runtime/onetake-browsers")}
    python = project / "runtime/onetake-python312/bin/python"
    probe = """import importlib.metadata as m,json,os,sys
from pathlib import Path
import playwright
manifest=json.loads((Path(playwright.__file__).parent/'driver/package/browsers.json').read_text())
revision=next(x['revision'] for x in manifest['browsers'] if x['name']=='chromium-headless-shell')
cache=Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])/('chromium_headless_shell-'+revision)
files=[p for p in cache.rglob('*') if p.is_file() and p.name in {'chrome-headless-shell','headless_shell.exe'}]
if len(files)>1: raise ValueError('OneTake browser installation is ambiguous')
print(json.dumps({'browser':str(files[0]) if files else None,'python':list(sys.version_info[:2]),
 'packages':{k:m.version(k) for k in ['playwright','numpy','Pillow','scipy','matplotlib','fonttools','brotli']}}))
"""
    return json.loads(subprocess.check_output([str(python), "-c", probe], env=environment, text=True))


def prepare_runtime(project_root):
    project = Path(project_root).resolve(strict=True)
    environment = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(project / "runtime/onetake-browsers")}
    directory = project / "runtime/onetake-python312"
    python = directory / "bin/python"
    if not python.is_file():
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("OneTake Python environment is incomplete; no overwrite")
        base = shutil.which("python3.12")
        if not base:
            raise ValueError("OneTake requires Python 3.12")
        subprocess.run([base, "-m", "venv", str(directory)], check=True, timeout=60)
    script = ("import importlib.metadata as m,json; "
              "print(json.dumps({d:m.version(d) for d in " + repr(list(PACKAGES)) + "}))")
    versions = subprocess.run([str(python), "-c", script], capture_output=True, text=True)
    if versions.returncode:
        subprocess.run([str(python), "-m", "pip", "install",
                        *[f"{name}=={version}" for name, version in PACKAGES.items()]],
                       env=environment, check=True, timeout=240)
    elif json.loads(versions.stdout) != PACKAGES:
        raise ValueError("OneTake render package versions changed; no automatic replacement")
    if runtime_details(project)["browser"] is None:
        subprocess.run([str(python), "-m", "playwright", "install", "--only-shell", "chromium"],
                       env=environment, check=True, timeout=240)
    subprocess.run([str(python), "-c",
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()"],
        env=environment, check=True, timeout=60, capture_output=True, text=True)

"""Canonical locations inside the complete hd-talking-head package."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PACKAGE_ROOT / "scripts"
REFERENCES = PACKAGE_ROOT / "references"
ASSETS = PACKAGE_ROOT / "assets"
VENDOR = PACKAGE_ROOT / "vendor"
RUNTIME = PACKAGE_ROOT / "runtime"
ARCHIVES = PACKAGE_ROOT / "archives"

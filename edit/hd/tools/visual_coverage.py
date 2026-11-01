"""Authoritative runtime visual coverage policy.

Load the same policy used by the Skill CLI so callers cannot drift to a second
set of density or content-coverage rules.
"""
from __future__ import annotations
from scripts.package_paths import PACKAGE_ROOT

import importlib.util
import sys
from pathlib import Path

_SCRIPT = PACKAGE_ROOT / "scripts" / "audit_visual_coverage.py"
if str(_SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("_hd_visual_coverage_script", _SCRIPT)
if _spec is None or _spec.loader is None:
    raise ImportError(f"visual coverage implementation missing: {_SCRIPT}")
_impl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_impl)

audit = _impl.audit
require_aroll_window = _impl.require_aroll_window


def require_density(visual: dict, *, subtitles: dict | None = None,
                    treatment: dict | None = None, content_analysis: dict | None = None,
                    require_overlays: bool = False) -> dict:
    """Run the single density gate, allowing callers without subtitles."""
    empty = {"render_plan": {"cues": []}}
    return audit(visual, subtitles or empty, 20.0, content_analysis=content_analysis,
                 require_density=True, require_overlays=require_overlays, treatment=treatment)


__all__ = ["audit", "require_density", "require_aroll_window"]

"""Load the one maintained avatar contract; do not vendor another Skill copy."""
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[3] / "skill-development/hd-talking-head/scripts/avatar_profile.py"
    spec = importlib.util.spec_from_file_location("hd_shared_avatar_profile", path)
    if spec is None or spec.loader is None:
        raise ValueError("avatar profile Skill entrypoint is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_avatar(value, *, frames=None):
    return _load().validate_avatar(value, frames=frames)


def validate_plan_avatars(segments, *, source_sha256=None):
    return _load().validate_plan_avatars(segments, source_sha256=source_sha256)


def validate_avatar_plan_policy(segments):
    return _load().validate_avatar_plan_policy(segments)


def plan_avatar_policy(segments):
    return _load().plan_avatar_policy(segments)


def filter_chain(value, *, frames, fade_out=True):
    return _load().filter_chain(value, frames=frames, fade_out=fade_out)

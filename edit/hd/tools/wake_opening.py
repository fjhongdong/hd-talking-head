"""Validate the cover-driven first body shot without moving its audio clock."""
from __future__ import annotations
import hashlib
from pathlib import Path
from . import contract_artifacts

WAKE_CANDIDATE = 'lemo-wake:wake'


def managed(job):
    return ((Path(job.root) / 'job-context.json').exists()
            or (Path(job.root) / '00-user-provided').exists())


def validate(job, director, treatment):
    opening = treatment.get('skill_selection', {}).get('opening')
    has_wake = any(b.get('dependency_id') == 'lemo-wake' for s in director.get('segments', [])
                   for b in s.get('bindings', {}).values())
    if opening is None and not managed(job) and not has_wake:
        return None
    if (not isinstance(opening, dict) or set(opening) != {'segment_id', 'component_id', 'candidate_id'}
            or opening['candidate_id'] != WAKE_CANDIDATE):
        raise ValueError('New Skill jobs require the fixed lemo-wake/wake opening declaration')
    segment = director['segments'][0]
    if segment['segment_id'] != opening['segment_id'] or segment['start'] != 0:
        raise ValueError('Wake opening must be the first segment at t0')
    strategy = segment['visual_strategy']
    component = next((c for c in strategy['components'] if c['component_id'] == opening['component_id']), None)
    binding = segment.get('bindings', {}).get(opening['component_id'], {})
    if (strategy.get('mode') != 'single' or len(strategy['components']) != 1
            or strategy.get('composition', {}).get('family') != 'single_full_frame'
            or not component or component.get('kind') != 'code_generated' or component.get('layer_role') != 'base'
            or binding.get('dependency_id') != 'lemo-wake'
            or binding.get('entrypoint') != 'scripts/lemo_wake_adapter.py'
            or binding.get('producer_version') != '2.0.0'
            or binding.get('template_id') != 'lemo-wake/wake'):
        raise ValueError('Wake opening must use its complete native opaque template')
    if (segment.get('visual_intent', {}).get('presenter_presence') != 'hidden'
            or strategy.get('composition', {}).get('presenter_mode') != 'hidden'
            or strategy.get('composition', {}).get('avatar') is not None):
        raise ValueError('Wake opening must hide presenter and omit avatar')
    scenes = [s for s in treatment.get('scenes', []) if s.get('segment_id') == opening['segment_id']
              and s.get('component_id') == opening['component_id']]
    if len(scenes) != 1:
        raise ValueError('Wake opening needs one hash-bound native brief')
    from .overlay_alignment import _path
    brief_file = _path(job.job_dir, scenes[0]['brief_path'])
    if hashlib.sha256(brief_file.read_bytes()).hexdigest() != binding.get('brief_sha256'):
        raise ValueError('Wake opening brief changed')
    # Reuse the public validator; importing it does not install or render.
    import sys
    scripts = Path(__file__).resolve().parents[3] / 'skill-development/hd-talking-head/scripts'
    previous = sys.path[:]
    try:
        sys.path.insert(0, str(scripts))
        from lemo_wake_adapter import validate_brief, exact
        brief = validate_brief(brief_file.read_bytes())
        if (brief['purpose'] != 'opening' or brief['job_id'] != job.job_id
                or any(brief['source_binding'][key] != segment[key] for key in ('segment_id', 'start', 'end'))):
            raise ValueError('Wake opening brief belongs to another purpose, Job or clock')
        image = exact(job.job_dir, brief['image'])
    finally:
        sys.path[:] = previous
    from .visual_plan import _approved_artifact
    cover = _approved_artifact(job, 'cover', '04-cover/cover-delivery-raster.png')
    if image.resolve() != cover.resolve() or brief['image']['sha256'] != contract_artifacts.sha256_file(cover):
        raise ValueError('Wake opening must use the current approved cover PNG')
    return opening

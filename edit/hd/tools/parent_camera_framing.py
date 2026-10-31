"""Source-preserving framing for one already approved generated video.

The manifest contains measured frame-local crop rectangles. FFmpeg's existing
zoompan filter performs the crop/scale; this module never repairs source pixels,
changes the source clock, draws content, or supplies a replacement timeline.
"""
from __future__ import annotations

import json
import math

from . import parent_static_labels

FIELD = 'parent_camera_framing'


def validate_descriptor(ref):
    return parent_static_labels.validate_descriptor(ref)


def validate_manifest(data, segment, component_id, *, media_sha256):
    required = {'schema_version', 'segment_id', 'component_id', 'source_binding',
                'source_media', 'normalized_media', 'source_frames', 'path', 'reason'}
    strategy = segment.get('visual_strategy', {})
    components = strategy.get('components', [])
    frames = round((segment['end'] - segment['start']) * 24)
    if (not isinstance(data, dict) or set(data) != required or data['schema_version'] != 1
            or (data['segment_id'], data['component_id']) != (segment['segment_id'], component_id)
            or strategy.get('mode') != 'single' or len(components) != 1
            or components[0].get('component_id') != component_id or components[0].get('kind') != 'ai_generated'
            or components[0].get('media_type') != 'video' or components[0].get('layer_role') != 'base'
            or components[0].get('layout_slot') != 'full_frame' or components[0].get('semantic_role') == 'evidence'
            or strategy.get('composition', {}).get('family') != 'single_full_frame'
            or not isinstance(data['reason'], str) or not data['reason'].strip()
            or data['source_frames'] != [0, frames] or frames < 1
            or not isinstance(data['path'], list) or len(data['path']) != frames):
        raise ValueError('camera framing must retain one approved explanatory source and its exact frame clock')
    source = data['source_binding']
    if (not isinstance(source, dict) or set(source) != {'aroll_sha256','start','end'}
            or source['start'] != segment['start'] or source['end'] != segment['end']):
        raise ValueError('camera framing speech window changed')
    for ref in (data['source_media'], data['normalized_media']):
        if not isinstance(ref, dict) or set(ref) != {'job_path','sha256','byte_count','media_type'} or ref['media_type'] != 'video':
            raise ValueError('camera framing needs original and normalized video identities')
        validate_descriptor({k:ref[k] for k in ('job_path','sha256','byte_count')})
    if data['normalized_media']['sha256'] != media_sha256:
        raise ValueError('camera framing does not reference the actual component media')
    for frame, crop in enumerate(data['path']):
        if (not isinstance(crop, dict) or set(crop) != {'frame','x','y','width','height'}
                or type(crop['frame']) is not int or crop['frame'] != frame
                or any(type(crop[k]) not in (int,float) or not math.isfinite(crop[k])
                       for k in ('x','y','width','height'))):
            raise ValueError('camera framing requires one finite crop per actual source frame')
        x,y,w,h = (crop[k] for k in ('x','y','width','height'))
        if (min(x,y) < 0 or min(w,h) <= 0 or x+w > 1080+1e-6 or y+h > 1920+1e-6
                or abs(h-w*16/9) > 1e-6):
            raise ValueError('camera crop must stay inside the original normalized portrait without fill or distortion')
    return data


def load(root, segment, component_id, *, media_sha256=None):
    binding = segment.get('bindings', {}).get(component_id, {})
    if FIELD not in binding:
        return None
    if binding.get('execution_mode') != 'reuse_completed_generated_media':
        raise ValueError('camera framing requires the completed generated-media source route')
    data = json.loads(parent_static_labels._file(root, binding[FIELD]).read_bytes())
    validate_manifest(data, segment, component_id, media_sha256=media_sha256 or binding.get('sha256'))
    for ref in (data['source_media'], data['normalized_media']):
        parent_static_labels._file(root, {k:ref[k] for k in ('job_path','sha256','byte_count')})
    return data


def filter_chain(data):
    """Use native per-input-frame crop/scale, with exactly one output per input."""
    def balanced_sum(terms):
        if len(terms) == 1:
            return terms[0]
        middle = len(terms) // 2
        return f'({balanced_sum(terms[:middle])}+{balanced_sum(terms[middle:])})'

    def expression(key):
        values = [1080/p['width'] if key == 'zoom' else p[key] for p in data['path']]
        # A linear sum exceeds libavutil's expression nesting limit on longer clips.
        return balanced_sum([f'eq(in,{frame})*{value:.15g}' for frame,value in enumerate(values)])
    return (f"zoompan=z='{expression('zoom')}':x='{expression('x')}':y='{expression('y')}'"
            ':d=1:s=1080x1920:fps=24,setsar=1')

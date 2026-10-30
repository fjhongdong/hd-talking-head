"""Bind already rasterized video-use labels; never draw or animate text here."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from . import contract_artifacts, motion_readability

FIELD = 'parent_static_labels'


def validate_descriptor(ref):
    if (type(ref) is not dict or set(ref) != {'job_path', 'sha256', 'byte_count'}
            or type(ref['job_path']) is not str
            or PurePosixPath(ref['job_path']).is_absolute()
            or any(p in {'', '.', '..'} for p in ref['job_path'].split('/'))
            or '\\' in ref['job_path']
            or not re.fullmatch(r'[0-9a-f]{64}', str(ref['sha256']))
            or type(ref['byte_count']) is not int or ref['byte_count'] <= 0):
        raise ValueError('static label requires an exact Job file descriptor')
    return ref


def _file(root, ref):
    validate_descriptor(ref)
    root = Path(root).resolve(strict=True)
    path = root / ref['job_path']
    if (not path.resolve(strict=True).is_relative_to(root) or path.is_symlink()
            or path.stat().st_nlink != 1 or not path.is_file()
            or path.stat().st_size != ref['byte_count']
            or contract_artifacts.sha256_file(path) != ref['sha256']):
        raise ValueError('static label file identity changed')
    return path


def load(root, segment, component_id):
    """Check fixed PNGs and the real text inputs used to rasterize them.

    The host uses video-use's existing PIL route to produce these PNGs. A
    manifest is production input, never OCR evidence or proof of cursor tracking.
    """
    binding = segment.get('bindings', {}).get(component_id, {})
    if FIELD not in binding:
        return []
    if binding.get('execution_mode') != 'reuse_completed_generated_media':
        raise ValueError('static labels require the completed generated-media route')
    from PIL import Image
    source = json.loads(_file(root, binding[FIELD]).read_text())
    if (type(source) is not dict
            or set(source) != {'schema_version', 'segment_id', 'component_id', 'labels'}
            or type(source['schema_version']) is not int or source['schema_version'] != 1
            or (source['segment_id'], source['component_id']) != (segment['segment_id'], component_id)
            or type(source['labels']) is not list or not source['labels']):
        raise ValueError('static label manifest differs from its visual target')
    frames = round((segment['end'] - segment['start']) * 24)
    avatar = segment.get('visual_strategy', {}).get('composition', {}).get('avatar', {})
    start = avatar.get('entrance', {}).get('frames', 0)
    end = frames - avatar.get('exit', {}).get('frames', 0)
    labels = []
    for label in source['labels']:
        if (type(label) is not dict or set(label) != {'content_ref', 'image', 'x', 'y', 'start_frame', 'end_frame'}
                or any(type(label[k]) is not int for k in ('x', 'y', 'start_frame', 'end_frame'))
                or not start <= label['start_frame'] < label['end_frame'] <= end
                or label['end_frame'] - label['start_frame'] < 12):
            raise ValueError('static labels need a fixed position and stable approved frame window')
        ref = label['content_ref']
        if (type(ref) is not dict or set(ref) != {'path', 'sha256', 'pointer', 'value'}
                or type(ref['value']) is not str or ref['value'] not in segment['visible_text']):
            raise ValueError('static label wording is not in the approved visible text')
        motion_readability._inside(Path(root), ref)
        image_path = _file(root, label['image'])
        with Image.open(image_path) as image:
            width, height = image.size
            if (image.format != 'PNG' or image.mode != 'RGBA' or image.getbbox() is None
                    or image.getchannel('A').getextrema()[0] == 255):
                raise ValueError('static label must be a real transparent RGBA PNG')
        if (label['x'] < 40 or label['y'] < 120 or label['x'] + width > 1040
                or label['y'] + height > 1380):
            raise ValueError('static label is outside the parent text-safe area')
        labels.append({**label, 'width': width, 'height': height})
    if {label['content_ref']['value'] for label in labels} != set(segment['visible_text']):
        raise ValueError('static labels must retain the exact approved visible text inventory')
    return labels


def validate_targets(labels, targets):
    """Bind the existing readability gate to precisely the inputs we composite."""
    for label in labels:
        matches = [t for t in targets if t['content_ref'] == label['content_ref']]
        if not matches:
            raise ValueError('static label is missing its real readability target')
        for target in matches:
            box = target['region']
            if (box['x'] < label['x'] or box['y'] < label['y']
                    or box['x'] + box['width'] > label['x'] + label['width']
                    or box['y'] + box['height'] > label['y'] + label['height']
                    or any(w['start'] < label['start_frame'] / 24
                           or w['end'] > label['end_frame'] / 24 for w in target['windows'])):
                raise ValueError('static label target differs from its actual placement or frame window')
    if any(t['content_ref'] not in [label['content_ref'] for label in labels] for t in targets):
        raise ValueError('static label readability cites an unrendered text source')


def compose(command, snapshots, labels):
    """Use the existing FFmpeg PNG overlay route after native media composition."""
    if not labels:
        return command
    command = list(command)
    index = command.index('-filter_complex')
    first = command[:index].count('-i')
    graph = command[index + 1]
    if graph.count('[out]') != 1:
        raise ValueError('static labels require the existing segment output')
    graph = graph.replace('[out]', '[parent_labels_base]')
    current = 'parent_labels_base'
    for i, (path, label) in enumerate(zip(snapshots, labels, strict=True)):
        graph += (f';[{first + i}:v]format=rgba,setpts=PTS-STARTPTS+'
                  f"{label['start_frame']}/24/TB[parent_label_{i}]"
                  f';[{current}][parent_label_{i}]overlay={label["x"]}:{label["y"]}:'
                  'eof_action=pass:shortest=0:'
                  f"enable='between(n,{label['start_frame']},{label['end_frame'] - 1})'[parent_labels_{i}]")
        current = f'parent_labels_{i}'
    graph += f';[{current}]format=yuv420p[out]'
    command[index + 1] = graph
    inputs = [value for path in snapshots for value in ('-loop', '1', '-framerate', '24', '-i', str(path))]
    command[index:index] = inputs
    return tuple(command)

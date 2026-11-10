"""Call the complete pinned Anidoodle Skill and consume its actual native result."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __name__ == '__main__' and Path(__file__).name == '<stdin>':
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument('--skill-root', required=True, type=Path)
    SKILL = bootstrap.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from package_paths import PACKAGE_ROOT
    SKILL = PACKAGE_ROOT
sys.path[:0] = [str(SKILL), str(SKILL / 'scripts')]

from adapter_kit import sha256_file as sha, validate_source_binding, ffprobe_json
from edit.hd.tools import contract_artifacts as artifacts
from motion_native_skill_adapter import (relative, path, descriptor, exact, task_source,
    approved_task, parent_input_facts, project_files, _inputs, _execution_job, _run_native_process)
from anidoodle_native_runtime import check as check_runtime, validate_identity, RENDERER_VERSION

PROJECT = SKILL
ENTRY = 'scripts/anidoodle_native_adapter.py'
DEPENDENCY_ID = 'anidoodle'
VERSION = '1.0.0'
COMMIT = '9c20e77467be393e54c7193611eeec2f7bfb8cc7'
SOURCE_SHA256 = '97149844971ed89f0fd9f0ddd3d43edde664eb65a51f1b82ae82b7f70bc0292f'


def source_root(project=PROJECT, *, dependency_id=DEPENDENCY_ID):
    if dependency_id != DEPENDENCY_ID:
        raise ValueError('Unknown Anidoodle dependency')
    project = Path(project).resolve(strict=True)
    record_path = project / 'references/anidoodle-native-source.json'
    if sha(record_path) != SOURCE_SHA256:
        raise ValueError('Anidoodle source identity record changed')
    record = json.loads(record_path.read_bytes())
    if record['commit'] != COMMIT:
        raise ValueError('Anidoodle upstream revision changed')
    root = path(project, record['source_root'])
    def verify(inventory):
        files = {p.relative_to(root).as_posix() for p in inventory if p.is_file() and not p.is_symlink()}
        links = {p.relative_to(root).as_posix(): str(p.readlink()) for p in inventory if p.is_symlink()}
        if files != set(record['files']) or links != record.get('symlinks', {}):
            raise ValueError('The complete unchanged Anidoodle repository is required')
        for name, digest in record['files'].items():
            target = root / relative(name)
            if target.is_symlink() or sha(target) != digest:
                raise ValueError('Anidoodle vendor source changed: ' + name)
    from native_result_reuse import source_unchanged
    return source_unchanged(project, ('anidoodle', DEPENDENCY_ID), root, verify, records=(record_path,))


def load_template_catalog(project=PROJECT, *, dependency_id=DEPENDENCY_ID):
    source_root(project, dependency_id=dependency_id)
    return json.loads((Path(project) / 'references/anidoodle-template-catalog.json').read_bytes())['native_paths']


def describe_candidates(project=PROJECT):
    return load_template_catalog(project)


def _template(brief, project=PROJECT):
    rows = load_template_catalog(project)
    row = next((r for r in rows if r['template_id'] == 'anidoodle/' + brief['template_id']), None)
    if row is None:
        raise ValueError('Unknown original Anidoodle registry style')
    return row


def validate_brief(payload, *, dependency_id=DEPENDENCY_ID):
    brief = json.loads(payload)
    fields = {'schema_version', 'dependency_id', 'job_id', 'source_binding', 'composition', 'alpha',
        'canvas_transport', 'template_request', 'template_id', 'semantic_goal', 'transcript', 'word_anchors',
        'speech', 'materials', 'authorization', 'project_directory', 'result_record_path', 'task_source', 'native_options'}
    if (not isinstance(brief, dict) or set(brief) != fields or brief['schema_version'] != 2
            or dependency_id != DEPENDENCY_ID or brief['dependency_id'] != DEPENDENCY_ID
            or any(not isinstance(brief[k], str) or not brief[k].strip()
                   for k in ('job_id', 'template_id', 'semantic_goal', 'transcript'))
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', brief['template_id'])
            or brief['canvas_transport'] != 'identity' or brief['native_options'] != []
            or type(brief['alpha']) is not bool):
        raise ValueError('Invalid Anidoodle native task brief')
    task = brief['task_source']
    if (not isinstance(task, dict) or set(task) != {'semantic_row_id', 'quote', 'semantic', 'required_change', 'component_brief'}
            or any(not isinstance(v, str) or not v.strip() for v in task.values())
            or brief['semantic_goal'] != task['semantic']):
        raise ValueError('Anidoodle requires its approved semantic task source')
    validate_source_binding(brief['source_binding'], 'Invalid Anidoodle approved source clock')
    c = brief['composition']
    if (not isinstance(c, dict) or set(c) != {'width', 'height', 'fps', 'frames'}
            or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or type(c['frames']) is not int or c['frames'] < 1
            or abs((brief['source_binding']['end'] - brief['source_binding']['start']) * 24 - c['frames']) > 1e-6):
        raise ValueError('Anidoodle requires the approved portrait 24fps integer-frame clock')
    req = brief['template_request']
    if (not isinstance(req, dict) or set(req) != {'semantic_family', 'information_units', 'numeric_values', 'numeric_scale'}
            or not isinstance(req['semantic_family'], str) or not req['semantic_family'].strip()
            or type(req['information_units']) is not int or req['information_units'] < 1
            or not isinstance(req['numeric_values'], list)
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in req['numeric_values'])
            or req['numeric_scale'] not in ({'linear', 'log'} if req['numeric_values'] else {'not_applicable'})):
        raise ValueError('Invalid Anidoodle semantic/numeric input')
    if not isinstance(brief['materials'], list) or not isinstance(brief['authorization'], dict):
        raise ValueError('Anidoodle requires actual material and resource authorization')
    if not isinstance(brief['word_anchors'], list) or not brief['word_anchors']:
        raise ValueError('Anidoodle requires exact local word anchors')
    for word in brief['word_anchors']:
        if (not isinstance(word, dict) or set(word) != {'text', 'start', 'end'}
                or not isinstance(word['text'], str) or not word['text']
                or any(type(word[k]) not in (int, float) or not math.isfinite(word[k]) for k in ('start', 'end'))
                or not 0 <= word['start'] < word['end'] <= c['frames'] / 24):
            raise ValueError('Anidoodle word anchors must use the exact scene local clock')
    if relative(brief['project_directory']).parts[0] != 'native-projects':
        raise ValueError('Anidoodle authored project belongs in native-projects')
    result = relative(brief['result_record_path'])
    if result.parts[0] != 'native-inputs' or result.suffix != '.json':
        raise ValueError('Anidoodle result belongs in a native-inputs JSON record')
    return brief


def validate_selected_inputs(job, director, treatment, *, dependency_id=None):
    from edit.hd.tools.visual_plan import _approved_artifact
    scenes = {(s.get('segment_id'), s.get('component_id')): s for s in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if binding.get('dependency_id') != DEPENDENCY_ID or dependency_id not in {None, DEPENDENCY_ID}:
                continue
            scene = scenes.get((segment['segment_id'], cid), {})
            if not isinstance(scene.get('brief_path'), str):
                raise ValueError('Selected Anidoodle task requires its actual brief')
            brief_path = path(job.job_dir, scene['brief_path'])
            payload = brief_path.read_bytes(); brief = validate_brief(payload)
            expected = task_source(director, treatment, segment['segment_id'], cid)
            beats = [b for group in ('beats', 'overlay_beats')
                     for b in treatment['skill_selection'].get(group, [])
                     if (b['segment_id'], b['component_id']) == (segment['segment_id'], cid)]
            arroll = sha(_approved_artifact(job, 'edit_structure', '06-edit-structure/edited-aroll.mp4'))
            if (any(brief['task_source'].get(k) != expected.get(k) for k in ('semantic_row_id', 'quote', 'semantic'))
                    or not beats or brief['transcript'] != beats[0]['transcript']
                    or sha(brief_path) != binding.get('brief_sha256') or brief['job_id'] != job.job_id
                    or brief['source_binding'] != {'aroll_sha256': arroll, 'segment_id': segment['segment_id'],
                                                   'start': segment['start'], 'end': segment['end']}
                    or binding.get('template_id') != 'anidoodle/' + brief['template_id']):
                raise ValueError('Anidoodle selected inputs differ from approved meaning, source or clock')
            _template(brief); _inputs(job.job_dir, brief)


def native_task(job, recipe, component, brief_path, *, approved_task_source, defer_runtime=False):
    brief_path = Path(brief_path)
    brief = validate_brief(brief_path.read_bytes())
    row = _template(brief)
    if (brief['job_id'] != job.job_id or sha(brief_path) != component['brief_sha256']
            or any(brief['task_source'].get(k) != approved_task_source.get(k)
                   for k in ('semantic_row_id', 'quote', 'semantic'))):
        raise ValueError('Anidoodle task differs from the confirmed parent binding')
    _inputs(job.job_dir, brief)
    runtime = ({'status': 'pending', 'check_argv': [sys.executable, str(PROJECT / ENTRY), '--probe']}
               if defer_runtime else check_runtime(PROJECT))
    return {'action': 'execute_native_skill', 'dependency_id': DEPENDENCY_ID, 'native_template': row,
        'native_instructions': row['native_instructions'], 'native_options': [], 'task_source': brief['task_source'],
        'template_id': row['template_id'], 'skill_path': str(PROJECT / row['skill_path']),
        'job_dir': str(job.job_dir), 'brief_path': str(brief_path), 'brief_sha256': sha(brief_path),
        'project_directory': str(path(job.job_dir, brief['project_directory'])), 'runtime': runtime,
        'segment_id': recipe['segment_id'], 'component_id': component['component_id'],
        'requirements': {**brief['composition'], 'alpha': brief['alpha'], 'silent': True,
            'canvas_transport': 'identity', 'semantic_goal': brief['semantic_goal'],
            'transcript': brief['transcript'], 'word_anchors': brief['word_anchors'],
            'authorization': brief['authorization']},
        'speech': str(path(job.job_dir, brief['speech']['job_path'])),
        'speech_window': {'start': 0, 'end': brief['composition']['frames'] / 24},
        'source_binding': brief['source_binding'],
        'materials': [str(path(job.job_dir, r['job_path'])) for r in brief['materials']],
        'result_record_path': brief['result_record_path'],
        'next': ('Read and execute the complete pinned Anidoodle Skill, selected style recipe and module, '
            'and the native workflow for this task. Use native scaffold.mjs --linked in the Job project; '
            'the complete original engine stays in vendor. The original Skill owns story, look, layout, '
            'choreography, source creation and native QA. Parent supplies approved meaning, exact word '
            'clock, materials, dimensions and actual avatar/subtitle safe zones only. Do not reuse an '
            'unchanged demo as current content. Keep vendor unchanged, and write no generated files there. '
            'Use the checked runtime environment unchanged for the native tools. Build a silent film '
            'without audio/narration/music; do not synthesize TTS or download the sound pack. For Chinese '
            'use Canvas fillText with an available CJK face or native launchLook fonts/registerFaces; '
            'never pass Chinese to Latin-only drafting/lettering/scrapbook glyphs. For alpha author '
            'an isolated subject without full-frame paper/background or g.paper; no encoder flag makes '
            'an opaque style demo transparent. A local backing under a label is allowed. Run native '
            'look, craft and final ship checks. Call capture_render with the direct original '
            '[node,engine/tools/render.mjs,<filmId>,--out,out/native.webm|out/native.mp4,--workers,1]. '
            'For alpha the bridge explicitly converts the native VP9 alpha into silent ProRes4444 '
            'without cropping or retiming and checks decoded clear and visible pixels. Then '
            'publish_completed; pending creative work is not completed media.')}


def _project_files(root, directory):
    # Native build/cache folders are generated outputs, never authored inputs.
    return [r for r in project_files(root, directory)
            if not {'.tmp', '.cache', 'dist'} & set(Path(r['job_path']).relative_to(Path(directory).relative_to(root)).parts)]


def _render_command(root, brief, argv, runtime):
    directory = path(root, brief['project_directory'])
    engine = source_root() / 'skills/anidoodle/engine'
    if (not isinstance(argv, list) or len(argv) != 7 or argv[0] != runtime['tools']['node']
            or Path(argv[1]).resolve(strict=True) != engine / 'tools/render.mjs'
            or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', argv[2])
            or argv[3:] != ['--out', 'out/native.webm' if brief['alpha'] else 'out/native.mp4', '--workers', '1']):
        raise ValueError('Anidoodle requires its exact unchanged native full-film render command')
    marker = json.loads((directory / 'anidoodle-project.json').read_bytes())
    if (marker.get('linked') is not True or marker.get('engine') != str(engine)
            or marker.get('film') != argv[2]):
        raise ValueError('Anidoodle requires its original linked scaffold project')
    return directory, engine, directory / argv[4]


def _normalization_command(runtime, raw, output):
    return [runtime['tools']['ffmpeg'], '-y', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(raw),
            '-map', '0:v:0', '-an', '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le',
            '-r', '24', '-color_range', 'tv', str(output)]


def probe(video, *, alpha=False):
    data = ffprobe_json(shutil.which('ffprobe') or 'ffprobe', video)
    streams = data['streams']
    if (len(streams) != 1 or streams[0].get('codec_type') != 'video'
            or streams[0].get('avg_frame_rate') != '24/1'
            or (streams[0].get('width'), streams[0].get('height')) != (1080, 1920)
            or (alpha and (streams[0].get('codec_name') != 'prores'
                           or not streams[0].get('pix_fmt', '').startswith('yuva')))
            or (not alpha and (streams[0].get('codec_name') != 'h264'
                               or streams[0].get('pix_fmt') != 'yuv420p'))):
        raise ValueError('Anidoodle delivery must be silent portrait 24fps with its requested real codec')
    return {'width': 1080, 'height': 1920, 'fps': 24,
            'frames': int(streams[0].get('nb_read_frames') or streams[0]['nb_frames'])}


def actual_alpha(video):
    pixels = subprocess.check_output([shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-i', str(video),
        '-vf', 'alphaextract,scale=64:114', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'], timeout=120)
    size = 64 * 114
    frames = [pixels[i:i + size] for i in range(0, len(pixels), size)]
    if not frames or any(len(f) != size for f in frames):
        raise ValueError('Cannot decode Anidoodle alpha pixels')
    visible = [f for f in frames if max(f) > 240]
    if not visible or any(min(f) >= 10 for f in visible):
        raise ValueError('Anidoodle alpha output contains an opaque full-frame background')
    return {'decoded_frames': len(frames), 'visible_frames': len(visible),
            'min_alpha': min(min(f) for f in frames), 'max_alpha': max(max(f) for f in frames)}


def capture_render(job_dir, brief_path, argv, *, native_preparations=None):
    if native_preparations is not None:
        raise ValueError('Anidoodle uses its original linked engine without external preparations')
    job = _execution_job(job_dir)
    root = Path(job_dir).resolve(strict=True)
    brief_path = Path(brief_path).resolve(strict=True); brief_path.relative_to(root)
    payload = brief_path.read_bytes(); brief = validate_brief(payload); _template(brief); _inputs(root, brief)
    if brief['job_id'] != job.job_id:
        raise ValueError('Anidoodle brief belongs to another Job')
    from edit.hd.tools.visual_confirmation import require_native_dispatch
    require_native_dispatch(job, DEPENDENCY_ID, brief_path, payload=payload)
    runtime = check_runtime(PROJECT)
    directory, engine, raw = _render_command(root, brief, argv, runtime)
    result_path = path(root, brief['result_record_path'])
    call_path = result_path.with_name(result_path.stem + '.render-call.json')
    output = raw.with_name('native_delivery.mov') if brief['alpha'] else raw
    if raw.exists() or output.exists() or call_path.exists():
        raise ValueError('Preserve native output and use a new revision directory')
    before = _project_files(root, directory)
    call = {'schema_version': 1, 'dependency_id': DEPENDENCY_ID, 'request_sha256': hashlib.sha256(payload).hexdigest(),
        'upstream_commit': COMMIT, 'native_script_sha256': sha(engine / 'tools/render.mjs'), 'argv': argv,
        'project_files': before, 'renderer_version': RENDERER_VERSION, 'runtime_identity': runtime['runtime_identity'],
        'status': 'running', 'exit_code': None, 'stdout': '', 'stderr': ''}
    call_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(call_path, call)
    try:
        environment = {**os.environ, **runtime['environment']}
        rendered = _run_native_process(argv, cwd=directory, env=environment)
        call.update(exit_code=rendered.returncode, stdout=rendered.stdout, stderr=rendered.stderr)
        if rendered.returncode:
            raise ValueError('Original Anidoodle render failed: ' + rendered.stderr[-1500:])
        ship = [runtime['tools']['node'], str(engine / 'tools/ship.mjs'), argv[2], '--file', argv[4]]
        checked = _run_native_process(ship, cwd=directory, env=environment)
        call['native_qa'] = {'argv': ship, 'exit_code': checked.returncode,
                             'stdout': checked.stdout, 'stderr': checked.stderr}
        if checked.returncode:
            raise ValueError('Original Anidoodle ship checks failed: ' + checked.stdout[-2500:])
        if brief['alpha']:
            normalize = _normalization_command(runtime, raw, output)
            _run_native_process(normalize, check=True)
            call['normalization'] = {'argv': normalize, 'exit_code': 0, 'source': descriptor(root, raw)}
            call['decoded_alpha'] = actual_alpha(output)
        if probe(output, alpha=brief['alpha']) != brief['composition']:
            raise ValueError('Anidoodle output differs from the approved exact clock')
        if before != _project_files(root, directory):
            raise ValueError('Anidoodle authored inputs changed during rendering')
        source_root()
        call['media'] = descriptor(root, output)
        call['status'] = 'completed'
    except BaseException as error:
        call['status'] = 'failed'; call['error'] = str(error)
        raise
    finally:
        artifacts.write_json_artifact(call_path, call)
    return call_path


def _verify_call(root, brief, payload, call):
    source_root(); _template(brief)
    validate_identity(PROJECT, call['runtime_identity'])
    runtime = {'tools': {k: v['path'] for k, v in call['runtime_identity']['tools'].items()}}
    directory, engine, raw = _render_command(root, brief, call['argv'], runtime)
    expected = raw.with_name('native_delivery.mov') if brief['alpha'] else raw
    qa = call.get('native_qa', {})
    if (call.get('status') != 'completed' or call.get('exit_code') != 0
            or call.get('request_sha256') != hashlib.sha256(payload).hexdigest()
            or call.get('upstream_commit') != COMMIT or call.get('dependency_id') != DEPENDENCY_ID
            or call.get('native_script_sha256') != sha(engine / 'tools/render.mjs')
            or call.get('renderer_version') != RENDERER_VERSION
            or qa.get('argv') != [runtime['tools']['node'], str(engine / 'tools/ship.mjs'), call['argv'][2], '--file', call['argv'][4]]
            or qa.get('exit_code') != 0 or exact(root, call['media']) != expected.resolve(strict=True)
            or _project_files(root, directory) != call['project_files']
            or probe(expected, alpha=brief['alpha']) != brief['composition']):
        raise ValueError('Anidoodle execution does not match approved inputs, native QA or output')
    for ref in call['project_files']:
        exact(root, ref)
    if brief['alpha']:
        normal = call.get('normalization', {})
        if (normal.get('argv') != _normalization_command(runtime, raw, expected)
                or normal.get('exit_code') != 0 or exact(root, normal['source']) != raw.resolve(strict=True)
                or actual_alpha(expected) != call.get('decoded_alpha')):
            raise ValueError('Anidoodle native alpha conversion or actual pixels changed')


def publish_completed(job_dir, brief_path, call_path, *, native_usage=None):
    if native_usage is not None:
        raise ValueError('Anidoodle uses one registry style identity')
    job = _execution_job(job_dir); root = Path(job_dir).resolve(strict=True)
    brief_path = Path(brief_path).resolve(strict=True); brief_path.relative_to(root)
    payload = brief_path.read_bytes(); brief = validate_brief(payload); _inputs(root, brief)
    if brief['job_id'] != job.job_id:
        raise ValueError('Anidoodle brief belongs to another Job')
    from edit.hd.tools.visual_confirmation import require_native_dispatch
    require_native_dispatch(job, DEPENDENCY_ID, brief_path, payload=payload)
    call = json.loads(Path(call_path).read_bytes()); _verify_call(root, brief, payload, call)
    target = path(root, brief['result_record_path'])
    if target.exists():
        raise ValueError('Preserve completed Anidoodle result and use a new revision')
    result = {'schema_version': 3, 'status': 'completed', 'dependency_id': DEPENDENCY_ID,
        'job_id': brief['job_id'], 'template_id': brief['template_id'], 'request_sha256': hashlib.sha256(payload).hexdigest(),
        'media': call['media'], 'media_probe': brief['composition'], 'alpha': brief['alpha'],
        'renderer_version': RENDERER_VERSION, 'render_call': descriptor(root, call_path)}
    artifacts.write_json_artifact(target, result)
    return target


def inspect_result(job_dir, payload, *, record_bytes=None):
    from native_result_reuse import inspect_unchanged
    brief = validate_brief(payload); source_root()
    data = record_bytes if record_bytes is not None else path(job_dir, brief['result_record_path']).read_bytes()
    return inspect_unchanged(PROJECT, job_dir, payload, data, brief, _inspect_result,
                             source_identity=('anidoodle', DEPENDENCY_ID))


def _inspect_result(job_dir, payload, data):
    brief = validate_brief(payload); _inputs(job_dir, brief)
    result = json.loads(data)
    expected = {'schema_version': 3, 'status': 'completed', 'dependency_id': DEPENDENCY_ID,
        'job_id': brief['job_id'], 'template_id': brief['template_id'],
        'request_sha256': hashlib.sha256(payload).hexdigest(), 'media_probe': brief['composition'],
        'alpha': brief['alpha'], 'renderer_version': RENDERER_VERSION}
    if any(result.get(k) != v for k, v in expected.items()):
        raise ValueError('Anidoodle result differs from its request')
    call = json.loads(exact(job_dir, result['render_call']).read_bytes())
    _verify_call(Path(job_dir).resolve(strict=True), brief, payload, call)
    if result['media'] != call['media']:
        raise ValueError('Anidoodle result differs from its actual rendered media')
    return result


def load_result(job_dir, payload, *, expected_record, expected_renderer_version):
    brief = validate_brief(payload)
    if (not isinstance(expected_record, dict) or set(expected_record) != {'path', 'sha256', 'bytes'}
            or expected_record['path'] != brief['result_record_path']):
        raise ValueError('Approved Anidoodle result descriptor is required')
    data = path(job_dir, expected_record['path']).read_bytes()
    if len(data) != expected_record['bytes'] or hashlib.sha256(data).hexdigest() != expected_record['sha256']:
        raise ValueError('Anidoodle result changed after approval')
    result = inspect_result(job_dir, payload, record_bytes=data)
    if result['renderer_version'] != expected_renderer_version:
        raise ValueError('Anidoodle renderer changed after approval')
    return result


def create_adapter(project_root, python_executable, brief_loader, *, dependency_id=DEPENDENCY_ID, renderer_version=None):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    project = Path(project_root).resolve(strict=True)
    source_root(project, dependency_id=dependency_id); check_runtime(project, mode='reuse')
    renderer_version = renderer_version or RENDERER_VERSION
    entry_sha = sha(SKILL / ENTRY)
    launcher = Path(python_executable).absolute()
    launcher = launcher.parent.resolve(strict=True) / launcher.name
    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        payload = brief_loader(job, recipe, component); brief = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan['segments'] if s['segment_id'] == recipe['segment_id'])
        source = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment['shot_recipe'] or brief['job_id'] != job.job_id
                or brief['source_binding'] != {'aroll_sha256': source['sha256'], 'segment_id': segment['segment_id'],
                                               'start': segment['start'], 'end': segment['end']}
                or brief['template_request'] != json.loads(json.dumps(component['invocation_record']['template_request']))
                or component['template_id'] != 'anidoodle/' + brief['template_id']
                or component['source_sha256'] != entry_sha or sha(SKILL / ENTRY) != entry_sha
                or component['renderer_version'] != renderer_version
                or component['render_window'].get('start_frame') != 0
                or component['render_window'].get('end_frame') != brief['composition']['frames']
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': brief['alpha']}):
            raise ValueError('Anidoodle differs from the approved Job, recipe or clock')
        _template(brief, project); _inputs(job.job_dir, brief)
        return payload
    def media(job, recipe, component, payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected = native_result_descriptor(job, recipe['segment_id'], component['component_id'], hashlib.sha256(payload).hexdigest())
        result = load_result(job.job_dir, payload, expected_record=expected, expected_renderer_version=renderer_version)
        rows = [{'job_path': expected['path'], 'sha256': expected['sha256']}, result['media']]
        return tuple(ReferenceProcessMedia('motion-' + hashlib.sha256(r['job_path'].encode()).hexdigest()[:32],
            r['job_path'], r['sha256']) for r in rows)
    return ReferenceProcessAdapter(adapter_id='anidoodle-native-skill-v1', dependency_id=DEPENDENCY_ID,
        approved_executor='reference_adapter', dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer='HTMLCanvas',
        renderer_version=renderer_version, artifact_media_type='video', launcher=launcher,
        launcher_sha256=sha(launcher), self_contained_wrapper=True, brief_loader=guard,
        media_loader=media, timeout_seconds=120,
        argv_template=('{launcher}', '{entrypoint}', '--skill-root', str(SKILL), '--dependency-id', DEPENDENCY_ID,
                       '--brief', '{brief_path}', '--media-manifest', '{media_manifest_fd}', '--output', '{output_path}'))


def create_binding(adapter, brief_bytes):
    brief = validate_brief(brief_bytes)
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return {'producer_type': 'dependency', 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
        'producer_version': VERSION, 'primary_renderer': 'HTMLCanvas', 'renderer_version': adapter.renderer_version,
        'template_origin': 'custom_fallback', 'template_id': 'anidoodle/' + brief['template_id'],
        'template_version': VERSION, 'adaptation_level': 'structural',
        'verification_id': hashlib.sha256((adapter.entrypoint_sha256 + digest).encode()).hexdigest(),
        'source_entrypoint': ENTRY, 'source_sha256': adapter.entrypoint_sha256,
        'semantic_families': [brief['template_request']['semantic_family']],
        'capacity': {'min_units': 1, 'max_units': brief['template_request']['information_units']},
        'brief_sha256': digest, 'invocation_record': {'argv': [str(adapter.launcher), ENTRY, '--dependency-id', DEPENDENCY_ID],
        'status': 'planned', 'exit_code': None, 'template_request': brief['template_request']}}


def create_artifact_probe(*, ffprobe_executable):
    from edit.hd.tools.material_adapter import create_artifact_probe as factory
    return factory(ffprobe_executable=ffprobe_executable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--dependency-id', default=DEPENDENCY_ID, choices=[DEPENDENCY_ID])
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--brief', type=Path); parser.add_argument('--job-dir', type=Path, default=os.environ.get('BROLL_JOB_DIR'))
    parser.add_argument('--capture-render', action='store_true'); parser.add_argument('--argv-json')
    parser.add_argument('--publish', action='store_true'); parser.add_argument('--call', type=Path)
    parser.add_argument('--media-manifest', type=Path); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.probe:
        source_root(args.project_root); check_runtime(args.project_root)
        print(json.dumps({'schema_version': 1, 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'adapter_identity': {'adapter_type': 'ReferenceProcessAdapter',
            'approved_executor': 'reference_adapter', 'primary_renderer': 'HTMLCanvas'}}))
    elif args.capture_render:
        print(capture_render(args.job_dir, args.brief, json.loads(args.argv_json)))
    elif args.publish:
        print(publish_completed(args.job_dir, args.brief, args.call))
    else:
        job = _execution_job(args.job_dir)
        payload = args.brief.read_bytes(); brief = validate_brief(payload)
        if brief['job_id'] != job.job_id:
            raise ValueError('Anidoodle brief belongs to another Job')
        manifest = json.loads(args.media_manifest.read_bytes())
        if manifest['brief_sha256'] != hashlib.sha256(payload).hexdigest():
            raise ValueError('Frozen Anidoodle request changed')
        files = {r['media_ref']: r for r in manifest['media']}
        def read(name):
            ref = files['motion-' + hashlib.sha256(name.encode()).hexdigest()[:32]]
            data = Path('/dev/fd/' + str(ref['fd'])).read_bytes()
            if hashlib.sha256(data).hexdigest() != ref['sha256'] or len(data) != ref['byte_length']:
                raise ValueError('Frozen Anidoodle input changed')
            return data
        result = json.loads(read(brief['result_record_path']))
        if (result['request_sha256'] != hashlib.sha256(payload).hexdigest() or result['status'] != 'completed'
                or result['dependency_id'] != DEPENDENCY_ID or result['alpha'] != brief['alpha']
                or result['media_probe'] != brief['composition'] or result['renderer_version'] != RENDERER_VERSION):
            raise ValueError('Frozen Anidoodle result changed')
        video = read(result['media']['job_path'])
        if hashlib.sha256(video).hexdigest() != result['media']['sha256'] or len(video) != result['media']['byte_count']:
            raise ValueError('Frozen Anidoodle media changed')
        args.output.write_bytes(video)
        print(json.dumps({'dependency_id': DEPENDENCY_ID, 'template_id': brief['template_id'], 'output_sha256': sha(args.output)}))


if __name__ == '__main__':
    main()

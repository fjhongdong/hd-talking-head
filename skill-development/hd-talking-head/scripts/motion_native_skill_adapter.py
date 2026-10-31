"""Invoke whole pinned native motion Skills and consume their reviewed outputs.

Creative work belongs to the original Skill. This bridge passes a task, verifies
its original renderer execution, and binds that actual result to the Job.
"""
from __future__ import annotations
import argparse
import hashlib
import functools
import http.server
import threading
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
    SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
sys.path[:0] = [str(PROJECT), str(SKILL / 'scripts')]
from adapter_kit import sha256_file as sha, validate_source_binding
from edit.hd.tools import contract_artifacts as artifacts

ENTRY = 'scripts/motion_native_skill_adapter.py'
VERSION = '2.0.0'
SOURCES = {
    'barty-motion-graphics': ('barty-motion', '3d83d987d658601d8a1269eb691622bdcd427335',
                              '159fdeb7a278c355e2df10a356de32d48e582efa69122c73b3552147bc20e9ef'),
    'bang-motion': ('bang-motion', 'c1aa65e921c970d858705fcb4a53a8294d1a4131',
                    'fc87bd12a065a64b7b60717ed9288397bdd04831d4a1b5fa9d6c7869f9895bcb'),
}
SOURCES.update({
    'mg-styles-15': ('mg-styles-15', '49052d80bfaf9fa8412cc9710530e5e95a3b8d8c',
                     'd9c69dff2056be5c706af6a950f3b85a0364113ae8efa448929460842e61e615'),
    'video-shotcraft': ('video-shotcraft', '1266a3ec4831289c4d893d42dd5102723658039a',
                        'fddf513112a7a2b342398ff0711e194c91bb5a1787c18ff2cdd25611375b9c4b'),
})

def primary_renderer(dependency_id):
    return 'Remotion' if dependency_id == 'video-shotcraft' else 'HTMLCanvas'


BARTY_TEMPLATES = {'motion-broll', 'explainer-default', 'explainer-engaging', 'explainer-high-energy'}


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or Path(value).is_absolute()
            or '..' in Path(value).parts or Path(value).as_posix() != value):
        raise ValueError('Native motion requires a canonical relative path')
    return Path(value)


def path(root, value):
    root = Path(root).resolve(strict=True)
    target = root / relative(value)
    if not target.resolve().is_relative_to(root):
        raise ValueError('Native motion path escapes its root')
    return target


def descriptor(root, target):
    target = Path(target).resolve(strict=True)
    return {'job_path': target.relative_to(Path(root).resolve(strict=True)).as_posix(),
            'sha256': sha(target), 'byte_count': target.stat().st_size}


def exact(root, record):
    if (not isinstance(record, dict) or set(record) != {'job_path', 'sha256', 'byte_count'}
            or not re.fullmatch('[a-f0-9]{64}', str(record['sha256']))
            or type(record['byte_count']) is not int or record['byte_count'] < 1):
        raise ValueError('Invalid native motion file descriptor')
    target = path(root, record['job_path'])
    if target.stat().st_size != record['byte_count'] or sha(target) != record['sha256']:
        raise ValueError('Native motion input, source or result changed: ' + record['job_path'])
    return target


def source_root(project=PROJECT, *, dependency_id):
    if dependency_id not in SOURCES:
        raise ValueError('Unknown native motion dependency')
    name, commit, digest = SOURCES[dependency_id]
    project = Path(project).resolve(strict=True)
    record_path = project / 'skill-development/hd-talking-head/references' / (name + '-native-source.json')
    if sha(record_path) != digest:
        raise ValueError('Native motion source identity record changed')
    record = json.loads(record_path.read_bytes())
    if record['commit'] != commit:
        raise ValueError('Native motion source revision changed')
    root = path(project, record['source_root'])
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    links = {p.relative_to(root).as_posix(): str(p.readlink()) for p in root.rglob('*') if p.is_symlink()}
    if links != record.get('symlinks', {}) or any(not (root / name).resolve().is_relative_to(root) for name in links):
        raise ValueError('Complete native motion source symlinks changed')
    if actual != set(record['files']):
        raise ValueError('Complete unmodified native motion source is required')
    for name, digest in record['files'].items():
        item = root / relative(name)
        if item.is_symlink() or sha(item) != digest:
            raise ValueError('Native motion source changed: ' + name)
    return root


def load_template_catalog(project=PROJECT, *, dependency_id):
    source_root(project, dependency_id=dependency_id)
    name = SOURCES[dependency_id][0]
    catalog = json.loads((Path(project) / 'skill-development/hd-talking-head/references' /
                          (name + '-template-catalog.json')).read_bytes())
    if 'native_paths' in catalog:
        return catalog['native_paths']
    return [{'candidate_id': identity, **row} for identity, row in catalog['execution'].items()]


def _template(brief, project=PROJECT):
    dependency = brief['dependency_id']
    rows = load_template_catalog(project, dependency_id=dependency)
    identity = dependency + ':' + dependency + '/' + brief['template_id']
    selected = next((row for row in rows if row['candidate_id'] == identity), None)
    if selected is None:
        raise ValueError('Unknown original native motion template')
    duration = brief['composition']['frames'] / brief['composition']['fps']
    if ((selected.get('min_duration_seconds') is not None and duration < selected['min_duration_seconds'])
            or (selected.get('max_duration_seconds') is not None and duration > selected['max_duration_seconds'])):
        raise ValueError('Native motion clock is outside the explicitly declared original template duration')
    if dependency == 'barty-motion-graphics' and brief['template_id'] not in BARTY_TEMPLATES:
        raise ValueError('Unknown original Barty workflow')
    groups = {row['candidate_id'].split('/')[-1]: row.get('native_template_group') for row in rows}
    if dependency == 'video-shotcraft':
        if any(option not in {style['key'] for style in selected.get('styles', [])} for option in brief['native_options']):
            raise ValueError('Unknown selected native Shotcraft style variant')
        return source_root(project, dependency_id=dependency)
    if any(option not in groups for option in brief['native_options']):
        raise ValueError('Unknown original native motion option')
    narrative = [identity for identity in [brief['template_id'], *brief['native_options']]
                 if groups[identity] in {'opener', 'explainer'}]
    if narrative and brief['template_id'] != narrative[0]:
        raise ValueError('The selected native narrative workflow must remain the primary template')
    return source_root(project, dependency_id=dependency)


def validate_brief(payload, *, dependency_id=None):
    brief = json.loads(payload)
    required = {'schema_version', 'dependency_id', 'job_id', 'source_binding', 'composition', 'alpha',
                'canvas_transport', 'template_request', 'template_id', 'semantic_goal', 'transcript', 'word_anchors',
                'speech', 'materials', 'authorization', 'project_directory', 'result_record_path',
                'task_source', 'native_options'}
    if (not isinstance(brief, dict) or set(brief) != required or brief['schema_version'] != 2
            or brief['dependency_id'] not in SOURCES
            or (dependency_id is not None and brief['dependency_id'] != dependency_id)
            or any(not isinstance(brief[k], str) or not brief[k].strip()
                   for k in ('job_id', 'template_id', 'semantic_goal', 'transcript'))
            or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', brief['template_id'])):
        raise ValueError('Invalid native motion task brief')
    task = brief['task_source']
    if (not isinstance(task, dict) or set(task) != {'semantic_row_id', 'quote', 'semantic', 'required_change', 'component_brief'}
            or any(not isinstance(value, str) or not value.strip() for value in task.values())
            or brief['semantic_goal'] != task['semantic']):
        raise ValueError('Native motion requires its approved semantic task source')
    options = brief['native_options']
    if (not isinstance(options, list) or any(not isinstance(v, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', v) for v in options)
            or len(options) != len(set(options)) or brief['template_id'] in options
            or (brief['dependency_id'] not in {'bang-motion', 'video-shotcraft'} and options)):
        raise ValueError('Invalid original native motion options')
    if brief['canvas_transport'] != ('quarter_turn_cw' if brief['dependency_id'] == 'bang-motion' else 'identity'):
        raise ValueError('Invalid native canvas transport')
    validate_source_binding(brief['source_binding'], 'Invalid native motion source clock')
    c = brief['composition']
    if (not isinstance(c, dict) or set(c) != {'width', 'height', 'fps', 'frames'}
            or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or type(c['frames']) is not int or c['frames'] < 1
            or abs((brief['source_binding']['end'] - brief['source_binding']['start']) * 24 - c['frames']) > 1e-6):
        raise ValueError('Native motion requires the exact approved portrait 24fps clock')
    if type(brief['alpha']) is not bool or (brief['alpha'] and
            (brief['dependency_id'] != 'barty-motion-graphics' or brief['template_id'] != 'motion-broll')):
        raise ValueError('Only original Barty motion-broll supports transparent ProRes output')
    request = brief['template_request']
    if (not isinstance(request, dict) or set(request) != {'semantic_family', 'information_units', 'numeric_values', 'numeric_scale'}
            or not isinstance(request['semantic_family'], str) or not request['semantic_family'].strip()
            or type(request['information_units']) is not int or request['information_units'] < 1
            or not isinstance(request['numeric_values'], list)
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in request['numeric_values'])
            or request['numeric_scale'] not in ({'linear', 'log'} if request['numeric_values'] else {'not_applicable'})):
        raise ValueError('Invalid native motion semantic or numeric input')
    if (not isinstance(brief['materials'], list) or not isinstance(brief['authorization'], dict)
            or not isinstance(brief['word_anchors'], list) or not brief['word_anchors']):
        raise ValueError('Native motion requires real inputs, word times and resource authorization')
    for word in brief['word_anchors']:
        if (not isinstance(word, dict) or set(word) != {'text', 'start', 'end'}
                or not isinstance(word['text'], str) or not word['text']
                or any(type(word[k]) not in (int, float) or not math.isfinite(word[k]) for k in ('start', 'end'))
                or not 0 <= word['start'] < word['end'] <= c['frames'] / 24):
            raise ValueError('Native motion word anchors must use the scene local clock')
    if relative(brief['project_directory']).parts[0] != 'native-projects':
        raise ValueError('Native motion project must be separate from user inputs')
    result = relative(brief['result_record_path'])
    if result.parts[0] != 'native-inputs' or result.suffix != '.json':
        raise ValueError('Native motion result must be a native-inputs JSON record')
    return brief


def task_source(director, treatment, segment_id, component_id):
    """Derive the task from the parent semantic row, never from a self-certified brief."""
    key = {'segment_id': segment_id, 'component_id': component_id}
    rows = [row for group in ('overlay', 'broll') for row in treatment.get('semantic_lists', {}).get(group, [])
            if key in row.get('components', [])]
    beats = [beat for group in ('beats', 'overlay_beats')
             for beat in treatment.get('skill_selection', {}).get(group, [])
             if (beat.get('segment_id'), beat.get('component_id')) == (segment_id, component_id)]
    components = [component for segment in director['segments'] if segment['segment_id'] == segment_id
                  for component in segment['visual_strategy']['components'] if component['component_id'] == component_id]
    if len(rows) != 1 or len(beats) != 1 or len(components) != 1:
        raise ValueError('Native motion requires one actual parent semantic row and beat')
    row, beat, component = rows[0], beats[0], components[0]
    if beat.get('semantic_row_id') != row['row_id'] or beat.get('component_brief') != component['brief']:
        raise ValueError('Native motion task differs from the selected parent component')
    return {'semantic_row_id': row['row_id'], 'quote': row['quote'], 'semantic': row['semantic'],
            'required_change': beat['required_change'], 'component_brief': component['brief']}


def approved_task(brief):
    """Execution locations may change before result approval; the creative request may not."""
    return {key: value for key, value in brief.items() if key not in {'project_directory', 'result_record_path'}}


def _inputs(root, brief):
    for record in [brief['speech'], *brief['materials']]:
        exact(root, record)
    data = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', str(path(root, brief['speech']['job_path']))], text=True))
    if (len(data['streams']) != 1 or data['streams'][0].get('codec_type') != 'audio'
            or abs(float(data['format']['duration']) - brief['composition']['frames'] / 24) > 1 / 24):
        raise ValueError('Native motion speech must be the approved scene audio clip')


def check_selected_template_dependencies(job, director, treatment):
    """Run selected-only preparation gates even for planned future inputs."""
    from motion_native_runtime import check_template_dependencies
    scenes = {(row.get('segment_id'), row.get('component_id')): row for row in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if (binding.get('dependency_id'), binding.get('template_id')) != ('mg-styles-15', 'mg-styles-15/3d-render'):
                continue
            scene = scenes.get((segment['segment_id'], cid), {})
            relative_brief = scene.get('brief_path')
            if isinstance(relative_brief, str) and path(job.job_dir, relative_brief).is_file():
                brief_path = path(job.job_dir, relative_brief)
                payload = brief_path.read_bytes(); brief = validate_brief(payload, dependency_id='mg-styles-15')
                if sha(brief_path) != binding.get('brief_sha256') or brief['template_id'] != '3d-render':
                    raise ValueError('Selected native 3D task differs from its actual binding')
                if path(job.job_dir, brief['result_record_path']).is_file():
                    inspect_result(job.job_dir, payload)
                    continue
            check_template_dependencies(PROJECT, dependency_id='mg-styles-15', template_id='3d-render')


def validate_selected_inputs(job, director, treatment, *, dependency_id=None):
    from edit.hd.tools.visual_plan import _approved_artifact
    scenes = {(s.get('segment_id'), s.get('component_id')): s for s in treatment.get('scenes', [])}
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            dependency = binding.get('dependency_id')
            if dependency not in SOURCES or (dependency_id is not None and dependency != dependency_id):
                continue
            scene = scenes.get((segment['segment_id'], cid), {})
            if not isinstance(scene.get('brief_path'), str):
                raise ValueError('Selected native motion requires its existing task brief')
            payload = path(job.job_dir, scene['brief_path']).read_bytes()
            brief = validate_brief(payload, dependency_id=dependency)
            expected_task = task_source(director, treatment, segment['segment_id'], cid)
            beats = [beat for group in ('beats', 'overlay_beats')
                     for beat in treatment['skill_selection'].get(group, [])
                     if (beat['segment_id'], beat['component_id']) == (segment['segment_id'], cid)]
            if brief['task_source'] != expected_task or brief['transcript'] != beats[0]['transcript']:
                raise ValueError('Native motion task must derive from the approved parent semantic row')
            approved = sha(_approved_artifact(job, 'edit_structure', '06-edit-structure/edited-aroll.mp4'))
            if (hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256') or brief['job_id'] != job.job_id
                    or brief['source_binding'] != {'aroll_sha256': approved, 'segment_id': segment['segment_id'],
                                                   'start': segment['start'], 'end': segment['end']}
                    or binding.get('template_id') != dependency + '/' + brief['template_id']):
                raise ValueError('Native motion selected inputs differ from approved source, template or clock')
            _template(brief)
            _inputs(job.job_dir, brief)


def native_task(job, recipe, component, brief_path, *, approved_task_source):
    brief_path = Path(brief_path)
    brief = validate_brief(brief_path.read_bytes())
    root = _template(brief)
    from motion_native_runtime import check
    runtime = check(PROJECT, dependency_id=brief['dependency_id'])
    from motion_native_runtime import check_template_dependencies
    check_template_dependencies(PROJECT, dependency_id=brief['dependency_id'], template_id=brief['template_id'])
    if (brief['job_id'] != job.job_id or sha(brief_path) != component['brief_sha256']
            or brief['task_source'] != approved_task_source):
        raise ValueError('Native motion task differs from confirmed binding')
    _inputs(job.job_dir, brief)
    selected = next(row for row in load_template_catalog(dependency_id=brief['dependency_id'])
                    if row['candidate_id'] == brief['dependency_id'] + ':' + brief['dependency_id'] + '/' + brief['template_id'])
    original_skill = PROJECT / selected['skill_path']
    action = {'action': 'execute_native_skill', 'dependency_id': brief['dependency_id'],
            'native_template': selected,
            'native_instructions': selected.get('native_instructions', [selected['skill_path']]),
            'native_options': brief['native_options'], 'task_source': brief['task_source'],
            'template_id': brief['dependency_id'] + '/' + brief['template_id'],
            'skill_path': str(original_skill), 'job_dir': str(job.job_dir), 'brief_path': str(brief_path),
            'brief_sha256': component['brief_sha256'], 'project_directory': str(path(job.job_dir, brief['project_directory'])),
            'runtime': runtime, 'segment_id': recipe['segment_id'], 'component_id': component['component_id'],
            'requirements': {**brief['composition'], 'alpha': brief['alpha'], 'silent': True, 'canvas_transport': brief['canvas_transport'],
                'semantic_goal': brief['semantic_goal'], 'transcript': brief['transcript'],
                'word_anchors': brief['word_anchors'], 'authorization': brief['authorization']},
            'speech': str(path(job.job_dir, brief['speech']['job_path'])),
            'speech_window': {'start': 0, 'end': brief['composition']['frames'] / 24},
            'source_binding': brief['source_binding'],
            'materials': [str(path(job.job_dir, r['job_path'])) for r in brief['materials']],
            'result_record_path': brief['result_record_path'],
            'next': native_workflow_instructions(brief) if brief['dependency_id'] in {'mg-styles-15', 'video-shotcraft'} else 'Read and execute the complete original Skill. task_source.quote and semantic are the approved meaning, including required objects, relations, changes and exclusions. required_change and component_brief are replaceable presentation references; the native Skill owns creative planning, layout, choreography, scene code, native build and QA. Honor the selected primary template and native_options. Author only this Job project; keep all pinned source unchanged. Write rendered media only under the project out directory; retain authored inputs and materials outside it. Use the approved inputs and resource authorization. For motion-broll call the original engine/build.py then engine/render.js at 24fps. For explainers save the complete original embedded render.mjs verbatim in the Job project and link its node_modules to runtime.node_modules. Use capture_render, inspect the actual result, then publish_completed. For Bang read the full original SKILL and selected native instructions, author the whole portrait design, place only its outer 1080x1920 root at transform-origin:0 0 with transform:translateX(1920px) rotate(90deg), mark it data-native-canvas-transport=quarter_turn_cw, and preserve the internal OPENER clock. Copy scripts/export-frames.mjs verbatim into this Job project and link node_modules to runtime.node_modules. capture_render runs its original exporter and native FFmpeg encoding with transpose=2 to restore the entire portrait board without scaling, cropping or retiming. The parent owns voice, ordinary subtitles and final composition. Stop and diagnose a failed item; revise only that item within the approved task, retain earlier files and repeat actual QA. Never retry automatically. This is pending work, not a completed result.'}

    return action

def native_workflow_instructions(brief):
    shared = ('Execute the complete pinned native workflow and selected native instructions. The approved task_source, transcript, real materials and output specifications are inputs; the native workflow owns treatment, look, layout, choreography and scene code. Preserve every vendor file. Author this Job project only. Keep voice, ordinary subtitles and final composition in the parent. Render the exact portrait 24fps clock without audio or alpha. Inspect the actual result and publish_completed through the existing reviewed-result contract. Stop and diagnose failure; never retry automatically. This handoff is pending creative work, not completed evidence. ')
    if brief['dependency_id'] == 'mg-styles-15':
        return shared + ('MG has no SKILL.md: read README.md, the full selected prompts/*.md, its native source demo and rubric.md. Follow treatment → cue sheet → key-frame inspection → native motion → final render → honest critique. Replace creative seed and output specifications for this task; retain every selected signature feature. Omit soundtrack because this parent requires silent B-roll. Copy harness/render.mjs verbatim into project_directory/harness/render.mjs; link project_directory/node_modules to runtime.node_modules. Author scene/index.html with window.DEMO={width:1080,height:1920,fps:24,duration:<approved seconds>}, deterministic window.renderAt(t), window.__ready=true. For the 3d-render style follow its full Blender source workflow and render assets before the native browser compositor; missing Blender stops that selected style. Call capture_render with [node,harness/render.mjs,scene,--out,out/native.mp4,--w,1080,--h,1920,--fps,24,--duration,<seconds>,--workers,1,--noaudio]. Do not substitute an unrelated helper or copy an old film.')
    if brief['dependency_id'] == 'video-shotcraft':
        return shared + ('Read SKILL.md, selected recipe card (or template/TEMPLATE.md for ink-press), gallery/api/library.json and the exact demo TSX specified by the recipe. Use native single-shot mode for a selected card; use the full original multi-shot workflow for ink-press. Preserve the recipe purpose and tuned motion; camera, transition and rhythm components require their intended source scenes and are not independent semantic B-roll or transparent overlays. Follow native requirements for authentic materials, visual direction, frame inspection and final review. Build the current task Remotion project with src/index.ts, a NativeScene composition at 1080x1920, 24fps and the approved frame count. Link node_modules to runtime.node_modules. Render via the original @remotion/cli/remotion-cli.js render src/index.ts NativeScene out/native.mp4 --codec=h264 --pixel-format=yuv420p --color-space=bt709 --image-format=png --muted --concurrency=1 --browser-executable=<runtime.browser>; pass this exact argv to capture_render. Do not count the 150 sample variants as templates or substitute an unchanged demo for current-task creation.')
    return ''


def probe(video, *, alpha=False, native_range=False):
    streams = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-count_frames', '-show_streams', '-of', 'json', str(video)], text=True))['streams']
    if (len(streams) != 1 or streams[0].get('avg_frame_rate') != '24/1'
            or (streams[0].get('width'), streams[0].get('height')) != (1080, 1920)
            or (alpha and (streams[0].get('codec_name') != 'prores' or not streams[0].get('pix_fmt', '').startswith('yuva')))
            or (not alpha and (streams[0].get('codec_name') != 'h264' or streams[0].get('pix_fmt') not in ({'yuv420p', 'yuvj420p'} if native_range else {'yuv420p'})))):
        raise ValueError('Native motion output must be silent portrait 24fps with the requested codec and alpha')
    return {'width': 1080, 'height': 1920, 'fps': 24,
            'frames': int(streams[0].get('nb_read_frames') or streams[0]['nb_frames'])}


def embedded_renderer(skill):
    blocks = re.findall(r'^```js\n(.*?)^```', Path(skill).read_text(), re.M | re.S)
    matches = [b for b in blocks if b.startswith('// render.mjs:')]
    if len(matches) != 1:
        raise ValueError('Original Skill must contain its complete native renderer')
    return matches[0].encode()


def project_files(root, directory):
    directory = Path(directory).resolve(strict=True)
    directory.relative_to(Path(root).resolve(strict=True))
    # Output files are recorded separately. Native authored HTML/fragments and
    # their local assets remain bound; installed modules never belong to Job.
    return [descriptor(root, p) for p in sorted(directory.rglob('*')) if p.is_file()
            and p.relative_to(directory).parts[0] != 'out'
            and not set(p.relative_to(directory).parts) & {'node_modules', '.git'}]


def _render_command(root, brief, argv, runtime, *, check_runtime_links=True):
    native = _template(brief)
    directory = path(root, brief['project_directory'])
    if brief['dependency_id'] in {'mg-styles-15', 'video-shotcraft'}:
        return _new_native_render_command(root, brief, argv, runtime, directory, native, check_runtime_links=check_runtime_links)
    bang = brief['dependency_id'] == 'bang-motion'
    if (not isinstance(argv, list) or len(argv) < (4 if bang else 5) or argv[0] != runtime['tools']['node']
            or (not bang and argv[4] != '24')):
        raise ValueError('Capture requires a direct original native renderer call at 24fps')
    script = Path(argv[1]); script = script if script.is_absolute() else directory / script
    script = script.resolve(strict=True)
    html = Path(argv[2]); html = html if html.is_absolute() else directory / html
    html = html.resolve(strict=True); html.relative_to(directory.resolve())
    if 'out' in html.relative_to(directory.resolve()).parts:
        raise ValueError('Author native HTML outside the render output directory')
    if html.suffix != '.html':
        raise ValueError('Native rendering requires the authored HTML inside this Job project')
    output = Path(argv[3]); output = output if output.is_absolute() else directory / output
    if output.resolve().relative_to(directory.resolve()).parts[0] != 'out':
        raise ValueError('Native render outputs must stay in the separate project out directory')
    if bang:
        if (len(argv) != 4 or script != directory.resolve() / 'export-frames.mjs'
                or script.read_bytes() != (native / 'scripts/export-frames.mjs').read_bytes()
                or (check_runtime_links and (directory / 'node_modules').resolve(strict=True) != Path(runtime['node_modules']).resolve(strict=True))):
            raise ValueError('Bang must execute its verbatim original exporter with the prepared native runtime')
    elif brief['template_id'] == 'motion-broll':
        if script != native / 'skills/motion-broll/engine/render.js' or len(argv) != 5:
            raise ValueError('Capture must call the original Barty engine/render.js')
    else:
        if (script.parent != directory.resolve() or script.name != 'render.mjs'
                or script.read_bytes() != embedded_renderer(native / 'skills' / brief['template_id'] / 'SKILL.md')
                or not 5 <= len(argv) <= 7 or any(not v.isdigit() or int(v) < 1 for v in argv[5:])):
            raise ValueError('Explainer must execute its verbatim original embedded renderer')
        if check_runtime_links and (directory / 'node_modules').resolve(strict=True) != Path(runtime['node_modules']).resolve(strict=True):
            raise ValueError('Explainer must use the separately prepared native runtime')
        # The original explainer always creates this silent file, even when
        # optional audio is authored. The parent consumes that native output.
        output = output.with_name(output.stem + '_silent.mp4')
    if output.suffix != ('.mov' if brief['alpha'] else '.mp4'):
        raise ValueError('Native motion output extension differs from requested alpha')
    return directory, script, output


def _new_native_render_command(root, brief, argv, runtime, directory, native, *, check_runtime_links):
    if not isinstance(argv, list) or not all(isinstance(v, str) for v in argv) or len(argv) < 3 or argv[0] != runtime['tools']['node']:
        raise ValueError('Capture requires the original selected native renderer')
    if check_runtime_links and (directory / 'node_modules').resolve(strict=True) != Path(runtime['node_modules']).resolve(strict=True):
        raise ValueError('Native project must use its separately prepared pinned runtime')
    script = Path(argv[1]); script = script if script.is_absolute() else directory / script
    script = script.resolve(strict=True)
    if brief['dependency_id'] == 'mg-styles-15':
        if script != directory.resolve() / 'harness/render.mjs' or script.read_bytes() != (native / 'harness/render.mjs').read_bytes():
            raise ValueError('MG must execute its verbatim original harness renderer')
        seconds = str(brief['composition']['frames'] / 24)
        if len(argv) != 16 or argv[2] != 'scene' or argv[3] != '--out' or argv[5:] != ['--w','1080','--h','1920','--fps','24','--duration',seconds,'--workers','1','--noaudio']:
            raise ValueError('MG native capture requires the exact approved portrait clock, one worker and no audio')
        scene = directory / 'scene/index.html'
        output = Path(argv[4])
    else:
        expected = Path(runtime['node_modules']) / '@remotion/cli/remotion-cli.js'
        if script != expected.resolve(strict=True) or len(argv) != 13 or argv[2:5] != ['render','src/index.ts','NativeScene'] or argv[6:12] != ['--codec=h264','--pixel-format=yuv420p','--color-space=bt709','--image-format=png','--muted','--concurrency=1']:
            raise ValueError('Shotcraft must execute the original pinned Remotion CLI for the authored composition')
        browser = (runtime.get('browser') or runtime.get('runtime_identity', {}).get('browser', {}).get('path'))
        if browser and argv[12] != '--browser-executable=' + browser:
            raise ValueError('Shotcraft native browser differs from its checked runtime')
        if not argv[12].startswith('--browser-executable='):
            raise ValueError('Shotcraft requires its checked browser')
        scene = directory / 'src/index.ts'
        output = Path(argv[5])
    if not scene.resolve(strict=True).is_relative_to(directory.resolve()) or not scene.is_file():
        raise ValueError('Native authored scene must remain inside this Job project')
    output = output if output.is_absolute() else directory / output
    if output.resolve().relative_to(directory.resolve()).parts[0] != 'out' or output.suffix != '.mp4':
        raise ValueError('Native media must be a separate H264 project out artifact')
    return directory, script, output


def _frame_descriptors(root, frames):
    return [descriptor(root, p) for p in sorted(frames.glob('f*.png'))]


def _bang_encoding_command(runtime, frames, output):
    return [runtime['tools']['ffmpeg'], '-v','error','-n','-framerate','24','-i',str(frames / 'f%05d.png'),
            '-vf','transpose=2','-c:v','libx264','-pix_fmt','yuv420p','-crf','16','-video_track_timescale','24',str(output)]


def _capture_bang(root, directory, argv, output, brief, runtime, environment):
    """Serve authored native HTML, run the unchanged exporter, encode its PNGs."""
    frames = directory / 'out/native-frames'
    if frames.exists():
        raise ValueError('Preserve earlier original exported frames')
    html = Path(argv[2]); html = html if html.is_absolute() else directory / html
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    from urllib.parse import quote
    url = 'http://127.0.0.1:' + str(server.server_port) + '/' + quote(html.relative_to(directory).as_posix())
    # Static geometry validation only. The original exporter exclusively owns
    # OPENER.seek/seekFrame and frame sampling.
    script = """const p=require('puppeteer');(async()=>{const b=await p.launch({headless:'new'});const page=await b.newPage();await page.setViewport({width:1920,height:1080});await page.goto(process.argv[1]);const v=await page.evaluate(()=>{const e=document.querySelector('[data-native-canvas-transport="quarter_turn_cw"]');if(!e)return null;const s=getComputedStyle(e),r=e.getBoundingClientRect(),m=new DOMMatrix(s.transform);return {w:e.offsetWidth,h:e.offsetHeight,origin:s.transformOrigin,matrix:[m.a,m.b,m.c,m.d,m.e,m.f],bounds:[r.x,r.y,r.width,r.height]}});console.log(JSON.stringify(v));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})"""
    try:
        check = subprocess.run([runtime['tools']['node'], '-e', script, url], cwd=directory,
                               env=environment, check=True, capture_output=True, text=True, timeout=30)
        geometry = json.loads(check.stdout)
        if geometry != {'w':1080,'h':1920,'origin':'0px 0px','matrix':[0,1,-1,0,1920,0],'bounds':[0,0,1920,1080]}:
            raise ValueError('Bang requires the complete portrait board rotated once without scaling or cropping')
        result = subprocess.run(argv, cwd=directory,
            env={**environment, 'URL':url, 'FPS':'24', 'OUT':str(frames), 'SCALE':'1'},
            capture_output=True, text=True, timeout=1200)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    transport = {'mode':'quarter_turn_cw','encoding_filter':'transpose=2','geometry':geometry,
                 'frames_directory':frames.relative_to(root).as_posix(), 'frames':_frame_descriptors(root,frames)}
    if not result.returncode:
        if len(transport['frames']) != brief['composition']['frames']:
            raise ValueError('Bang original exporter frame count differs from approved clock')
        for index, item in enumerate(transport['frames']):
            if Path(item['job_path']).name != f'f{index:05d}.png':
                raise ValueError('Bang original frame sequence is incomplete')
        output.parent.mkdir(parents=True, exist_ok=True)
        command = _bang_encoding_command(runtime, frames, output)
        encoding = subprocess.run(command, capture_output=True, text=True, timeout=1200)
        transport['encode_argv'] = command
        transport['encode_exit_code'] = encoding.returncode
        if encoding.returncode:
            raise ValueError('Bang native PNG encoding failed: ' + encoding.stderr[-1500:])
    return result, transport


def _normalization_command(runtime, source, output):
    return [runtime['tools']['ffmpeg'], '-v', 'error', '-n', '-i', str(source),
            '-vf', 'scale=in_range=auto:out_range=tv', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-color_range', 'tv', '-crf', '16', '-an', '-video_track_timescale', '24', str(output)]


def capture_render(job_dir, brief_path, argv):
    root = Path(job_dir).resolve(strict=True)
    brief_path = Path(brief_path).resolve(strict=True); brief_path.relative_to(root)
    brief = validate_brief(brief_path.read_bytes()); _inputs(root, brief)
    from motion_native_runtime import check
    runtime = check(PROJECT, dependency_id=brief['dependency_id'])
    from motion_native_runtime import check_template_dependencies
    check_template_dependencies(PROJECT, dependency_id=brief['dependency_id'], template_id=brief['template_id'])
    directory, script, output = _render_command(root, brief, argv, runtime)
    argv = [argv[0], str(script), *argv[2:]]
    result_path = Path(brief['result_record_path'])
    call_path = path(root, result_path.with_name(result_path.stem + '.render-call.json').as_posix())
    original_output = (directory / argv[3] if brief['dependency_id'] == 'barty-motion-graphics'
                       and brief['template_id'] != 'motion-broll' else None)
    if output.exists() or call_path.exists() or (original_output is not None and original_output.exists()):
        raise ValueError('Preserve existing native output and use a new revision directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    before = project_files(root, directory)
    environment = {**os.environ, **runtime['environment'], 'NODE_PATH': runtime['node_modules']}
    if brief['dependency_id'] == 'bang-motion':
        result, transport = _capture_bang(root, directory, argv, output, brief, runtime, environment)
    else:
        result = subprocess.run(argv, cwd=directory, env=environment, capture_output=True, text=True, timeout=1200)
        transport = None
    if before != project_files(root, directory):
        raise ValueError('Native project source changed during rendering')
    record = {'schema_version': 1, 'dependency_id': brief['dependency_id'],
              'request_sha256': sha(brief_path), 'upstream_commit': SOURCES[brief['dependency_id']][1],
              'native_script_sha256': sha(script), 'argv': argv,
              'project_files': before, 'renderer_version': runtime['renderer_version'],
              'runtime_identity': runtime['runtime_identity'],
              'execution_runtime': {key: runtime[key] for key in ('tools', 'node_modules', 'renderer_version')},
              'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    if transport is not None:
        record['canvas_transport'] = transport
    # Retain the actual native call even when later codec/clock inspection fails.
    call_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(call_path, record)
    try:
        if not result.returncode and brief['dependency_id'] == 'barty-motion-graphics' and brief['template_id'] != 'motion-broll':
            if probe(output, native_range=True) != brief['composition']:
                raise ValueError('Original native renderer differs from the approved clock')
            raw = output
            output = raw.with_name(raw.stem + '_delivery.mp4')
            command = _normalization_command(runtime, raw, output)
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=1200)
            record['normalization'] = {'source': descriptor(root, raw), 'argv': command, 'exit_code': 0}
        if not result.returncode:
            if probe(output, alpha=brief['alpha']) != brief['composition']:
                raise ValueError('Native output differs from the exact approved clock')
            record['media'] = descriptor(root, output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        record['artifact_check_error'] = str(error)
        artifacts.write_json_artifact(call_path, record)
        raise
    call_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(call_path, record)
    if result.returncode:
        raise ValueError('Original native motion render failed: ' + result.stderr[-1500:])
    _template(brief)
    return call_path


def _verify_call(root, brief, payload, call):
    from motion_native_runtime import check, validate_runtime_identity
    check(PROJECT, dependency_id=brief['dependency_id'], mode='reuse')
    validate_runtime_identity(PROJECT, call['runtime_identity'], dependency_id=brief['dependency_id'])
    runtime = call['execution_runtime']
    if (runtime['renderer_version'] != call['runtime_identity']['renderer_version']
            or runtime['tools'] != {name: record['path'] for name, record in call['runtime_identity']['tools'].items()}):
        raise ValueError('Native execution runtime differs from its recorded identity')
    _, script, output = _render_command(root, brief, call['argv'], {**runtime, 'browser': call['runtime_identity']['browser']['path']}, check_runtime_links=False)
    if brief['dependency_id'] == 'barty-motion-graphics' and brief['template_id'] != 'motion-broll':
        original = output
        output = original.with_name(original.stem + '_delivery.mp4')
        normalization = call.get('normalization', {})
        if (normalization.get('argv') != _normalization_command(runtime, original, output)
                or normalization.get('exit_code') != 0 or exact(root, normalization['source']) != original.resolve(strict=True)
                or probe(original, native_range=True) != brief['composition']):
            raise ValueError('Native normalization differs from its original output')
    if (call['exit_code'] != 0 or call['dependency_id'] != brief['dependency_id']
            or call['request_sha256'] != hashlib.sha256(payload).hexdigest()
            or call['upstream_commit'] != SOURCES[brief['dependency_id']][1]
            or call['native_script_sha256'] != sha(script) or call['renderer_version'] != runtime['renderer_version']
            or exact(root, call['media']) != output.resolve(strict=True)):
        raise ValueError('Native execution does not match the current request, source or output')
    if brief['dependency_id'] == 'bang-motion':
        transport = call.get('canvas_transport', {})
        if transport.get('mode') != 'quarter_turn_cw' or transport.get('encoding_filter') != 'transpose=2':
            raise ValueError('Bang result lacks the native whole-board transport')
        frames = path(root, transport['frames_directory'])
        if (transport.get('encode_argv') != _bang_encoding_command(runtime, frames, output)
                or transport.get('encode_exit_code') != 0
                or len(transport['frames']) != brief['composition']['frames']
                or _frame_descriptors(root, frames) != transport['frames']):
            raise ValueError('Bang original exported frames changed')
    for item in call['project_files']:
        exact(root, item)
    if project_files(root, path(root, brief['project_directory'])) != call['project_files']:
        raise ValueError('Native authored project changed after rendering')
    if probe(output, alpha=brief['alpha']) != brief['composition']:
        raise ValueError('Native motion media differs from approved clock')


def publish_completed(job_dir, brief_path, call_path, *, qa_note):
    root = Path(job_dir).resolve(strict=True)
    payload = Path(brief_path).read_bytes(); brief = validate_brief(payload); _inputs(root, brief)
    if not isinstance(qa_note, str) or not qa_note.strip():
        raise ValueError('Native result requires actual motion and content QA')
    call = json.loads(Path(call_path).read_bytes()); _verify_call(root, brief, payload, call)
    target = path(root, brief['result_record_path'])
    if target.exists():
        raise ValueError('Preserve the completed native result and use a new revision')
    result = {'schema_version': 1, 'status': 'completed', 'dependency_id': brief['dependency_id'],
              'job_id': brief['job_id'], 'template_id': brief['template_id'],
              'request_sha256': hashlib.sha256(payload).hexdigest(), 'media': call['media'],
              'media_probe': brief['composition'], 'alpha': brief['alpha'],
              'renderer_version': call['renderer_version'], 'render_call': descriptor(root, call_path), 'qa_note': qa_note}
    artifacts.write_json_artifact(target, result)
    return target


def inspect_result(job_dir, payload, *, record_bytes=None):
    brief = validate_brief(payload); _inputs(job_dir, brief); _template(brief)
    data = record_bytes if record_bytes is not None else path(job_dir, brief['result_record_path']).read_bytes()
    result = json.loads(data)
    expected = {'schema_version': 1, 'status': 'completed', 'dependency_id': brief['dependency_id'],
                'job_id': brief['job_id'], 'template_id': brief['template_id'],
                'request_sha256': hashlib.sha256(payload).hexdigest(), 'media_probe': brief['composition'], 'alpha': brief['alpha']}
    if any(result.get(k) != v for k, v in expected.items()) or not str(result.get('qa_note', '')).strip():
        raise ValueError('Native motion result differs from its request or lacks QA')
    call = json.loads(exact(job_dir, result['render_call']).read_bytes())
    _verify_call(job_dir, brief, payload, call)
    if result['media'] != call['media'] or result['renderer_version'] != call['renderer_version']:
        raise ValueError('Native result differs from actual execution')
    return result


def load_result(job_dir, payload, *, expected_record, expected_renderer_version):
    brief = validate_brief(payload)
    if (not isinstance(expected_record, dict) or set(expected_record) != {'path', 'sha256', 'bytes'}
            or expected_record['path'] != brief['result_record_path']):
        raise ValueError('Approved native result descriptor is required')
    data = path(job_dir, expected_record['path']).read_bytes()
    if len(data) != expected_record['bytes'] or hashlib.sha256(data).hexdigest() != expected_record['sha256']:
        raise ValueError('Native result differs from reviewed version')
    result = inspect_result(job_dir, payload, record_bytes=data)
    if result['renderer_version'] != expected_renderer_version:
        raise ValueError('Native renderer differs from frozen component')
    return result


def create_adapter(project_root, python_executable, brief_loader, *, dependency_id, renderer_version=None):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    requested = Path(project_root).absolute(); project = requested.resolve(strict=True)
    if requested != project:
        raise ValueError('Native motion project root must be canonical and nonsymlinked')
    source_root(project, dependency_id=dependency_id)
    from motion_native_runtime import check, PACKAGES
    check(project, dependency_id=dependency_id, mode='reuse')
    renderer_version = renderer_version or '-'.join(PACKAGES[dependency_id])
    entry_sha = sha(SKILL / ENTRY); launcher = Path(python_executable).resolve(strict=True)

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary
        payload = brief_loader(job, recipe, component); brief = validate_brief(payload, dependency_id=dependency_id)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan['segments'] if s['segment_id'] == recipe['segment_id'])
        arroll = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment['shot_recipe'] or brief['job_id'] != job.job_id
                or brief['source_binding'] != {'aroll_sha256': arroll['sha256'], 'segment_id': segment['segment_id'],
                                               'start': segment['start'], 'end': segment['end']}
                or brief['template_request'] != json.loads(json.dumps(component['invocation_record']['template_request']))
                or component['template_id'] != dependency_id + '/' + brief['template_id']
                or component['source_sha256'] != entry_sha or sha(SKILL / ENTRY) != entry_sha
                or component['renderer_version'] != renderer_version
                or component['render_window'].get('start_frame') != 0
                or component['render_window'].get('end_frame') != brief['composition']['frames']
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': brief['alpha']}):
            raise ValueError('Native motion differs from approved Job, recipe or clock')
        _template(brief, project); _inputs(job.job_dir, brief)
        return payload

    def media_loader(job, recipe, component, payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected = native_result_descriptor(job, recipe['segment_id'], component['component_id'], hashlib.sha256(payload).hexdigest())
        result = load_result(job.job_dir, payload, expected_record=expected, expected_renderer_version=renderer_version)
        rows = [{'job_path': expected['path'], 'sha256': expected['sha256']}, result['media']]
        return tuple(ReferenceProcessMedia('motion-' + hashlib.sha256(r['job_path'].encode()).hexdigest()[:32],
                                           r['job_path'], r['sha256']) for r in rows)

    return ReferenceProcessAdapter(adapter_id=dependency_id + '-native-skill-v1', dependency_id=dependency_id,
        approved_executor='reference_adapter', dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer=primary_renderer(dependency_id),
        renderer_version=renderer_version, artifact_media_type='video', launcher=launcher,
        launcher_sha256=sha(launcher), self_contained_wrapper=True, brief_loader=guarded_loader,
        media_loader=media_loader, timeout_seconds=120,
        argv_template=('{launcher}', '{entrypoint}', '--skill-root', str(SKILL), '--dependency-id', dependency_id,
                       '--brief', '{brief_path}', '--media-manifest', '{media_manifest_fd}', '--output', '{output_path}'))


def create_binding(adapter, brief_bytes, reference_sample):
    brief = validate_brief(brief_bytes, dependency_id=adapter.dependency_id)
    return {'producer_type': 'dependency', 'dependency_id': adapter.dependency_id, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'primary_renderer': primary_renderer(adapter.dependency_id), 'renderer_version': adapter.renderer_version,
            'template_origin': 'custom_fallback', 'template_id': adapter.dependency_id + '/' + brief['template_id'],
            'template_version': VERSION, 'adaptation_level': 'structural',
            'verification_id': hashlib.sha256((adapter.entrypoint_sha256 + hashlib.sha256(brief_bytes).hexdigest()).encode()).hexdigest(),
            'source_entrypoint': ENTRY, 'source_sha256': adapter.entrypoint_sha256, 'sample_sha256': sha(reference_sample),
            'semantic_families': [brief['template_request']['semantic_family']],
            'capacity': {'min_units': 1, 'max_units': brief['template_request']['information_units']},
            'brief_sha256': hashlib.sha256(brief_bytes).hexdigest(),
            'invocation_record': {'argv': [str(adapter.launcher), ENTRY, '--dependency-id', adapter.dependency_id],
                                  'status': 'planned', 'exit_code': None, 'template_request': brief['template_request']}}


def create_artifact_probe(*, ffprobe_executable):
    from edit.hd.tools.material_adapter import create_artifact_probe as factory
    return factory(ffprobe_executable=ffprobe_executable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--dependency-id', required=True, choices=SOURCES)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--brief', type=Path); parser.add_argument('--job-dir', type=Path)
    parser.add_argument('--capture-render', action='store_true'); parser.add_argument('--argv-json')
    parser.add_argument('--publish', action='store_true'); parser.add_argument('--call', type=Path)
    parser.add_argument('--qa-note'); parser.add_argument('--media-manifest', type=Path); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.probe:
        from motion_native_runtime import check
        source_root(args.project_root, dependency_id=args.dependency_id)
        check(args.project_root, dependency_id=args.dependency_id)
        print(json.dumps({'schema_version': 1, 'dependency_id': args.dependency_id, 'entrypoint': ENTRY,
              'producer_version': VERSION, 'adapter_identity': {'adapter_type': 'ReferenceProcessAdapter',
              'approved_executor': 'reference_adapter', 'primary_renderer': primary_renderer(args.dependency_id)}}))
    elif args.capture_render:
        print(capture_render(args.job_dir, args.brief, json.loads(args.argv_json)))
    elif args.publish:
        print(publish_completed(args.job_dir, args.brief, args.call, qa_note=args.qa_note))
    else:
        payload = args.brief.read_bytes(); brief = validate_brief(payload, dependency_id=args.dependency_id)
        manifest = json.loads(args.media_manifest.read_bytes())
        if manifest['brief_sha256'] != hashlib.sha256(payload).hexdigest():
            raise ValueError('Frozen native motion request differs')
        files = {r['media_ref']: r for r in manifest['media']}
        def read(name):
            row = files['motion-' + hashlib.sha256(name.encode()).hexdigest()[:32]]
            data = Path('/dev/fd/' + str(row['fd'])).read_bytes()
            if hashlib.sha256(data).hexdigest() != row['sha256'] or len(data) != row['byte_length']:
                raise ValueError('Frozen native motion file differs')
            return data
        result = json.loads(read(brief['result_record_path']))
        if (result['request_sha256'] != hashlib.sha256(payload).hexdigest() or result['status'] != 'completed'
                or result['dependency_id'] != args.dependency_id):
            raise ValueError('Frozen native motion result differs')
        video = read(result['media']['job_path'])
        if hashlib.sha256(video).hexdigest() != result['media']['sha256'] or len(video) != result['media']['byte_count']:
            raise ValueError('Frozen native media differs from reviewed output')
        args.output.write_bytes(video)
        print(json.dumps({'dependency_id': args.dependency_id, 'template_id': brief['template_id'],
                          'output_sha256': hashlib.sha256(video).hexdigest()}))


if __name__ == '__main__':
    main()

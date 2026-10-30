"""Call the complete native Wake Skill; freeze and accept its original output.

The host performs Wake's creative workflow. This bridge never authors animation
code, chooses its internal FX, extracts layers, or substitutes a renderer.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

if __name__ == '__main__' and Path(__file__).name == '<stdin>':
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--skill-root', required=True, type=Path)
    SKILL = p.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
sys.path[:0] = [str(PROJECT), str(SKILL / 'scripts')]
from edit.hd.tools import contract_artifacts as artifacts
from edit.hd.tools.segment_render import re_full_segment_id
from adapter_kit import sha256_file as sha

DEPENDENCY_ID = 'lemo-wake'
ENTRY = 'scripts/lemo_wake_adapter.py'
VERSION = '2.0.0'
TEMPLATE_ID = 'lemo-wake/wake'
UPSTREAM_COMMIT = 'f070df8bdf891d792012aabc054582b16e04f759'
NATIVE_ENTRY = 'skills/wake/SKILL.md'
STEPS = {'init': 'new_project.py', 'render': 'render.mjs', 'encode': 'encode.py', 'qa': 'qa.py'}


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value
            or Path(value).is_absolute() or '..' in Path(value).parts
            or Path(value).as_posix() != value):
        raise ValueError('Wake requires a canonical Job-relative path')
    return Path(value)


def path(root, value):
    root = Path(root).resolve(strict=True)
    resolved = root / relative(value)
    if not resolved.resolve().is_relative_to(root):
        raise ValueError('Wake path escapes this Job')
    return resolved


def descriptor(root, item):
    file = Path(item).resolve(strict=True)
    return {'job_path': file.relative_to(Path(root).resolve(strict=True)).as_posix(),
            'sha256': sha(file), 'byte_count': file.stat().st_size}


def check_descriptor(d, *, project_src=None):
    minimum = 0 if isinstance(d, dict) and project_src is not None and d.get('job_path') == project_src + '/fonts.css' else 1
    if (not isinstance(d, dict) or set(d) != {'job_path', 'sha256', 'byte_count'}
            or not isinstance(d['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', d['sha256'])
            or type(d['byte_count']) is not int or d['byte_count'] < minimum):
        raise ValueError('Invalid Wake file descriptor')
    relative(d['job_path'])


def exact(root, d):
    check_descriptor(d)
    f = path(root, d['job_path'])
    if f.stat().st_size != d['byte_count'] or sha(f) != d['sha256']:
        raise ValueError('Wake input or native evidence changed: ' + d['job_path'])
    return f


def validate_brief(payload):
    b = json.loads(payload)
    required = {'schema_version', 'job_id', 'source_binding', 'image', 'purpose', 'composition',
                'semantic_goal', 'template_request', 'result_record_path'}
    if (not isinstance(b, dict) or set(b) not in (required, required | {'revision'})
            or type(b['schema_version']) is not int or b['schema_version'] != 1
            or not isinstance(b['job_id'], str) or not b['job_id'].strip()
            or b['purpose'] not in {'opening', 'body'}
            or not isinstance(b['semantic_goal'], str) or not b['semantic_goal'].strip()):
        raise ValueError('Invalid native Wake brief')
    s, c, r = b['source_binding'], b['composition'], b['template_request']
    if (not isinstance(s, dict) or set(s) != {'aroll_sha256', 'segment_id', 'start', 'end'}
            or not isinstance(s['aroll_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', s['aroll_sha256'])
            or not isinstance(s['segment_id'], str) or not re_full_segment_id(s['segment_id'])
            or any(type(s[k]) not in (int, float) or not math.isfinite(s[k]) for k in ('start', 'end'))
            or not 0 <= s['start'] < s['end']):
        raise ValueError('Invalid Wake source clock')
    if (not isinstance(c, dict) or set(c) != {'width', 'height', 'fps', 'frames'}
            or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or type(c['frames']) is not int or not 1 <= c['frames'] <= 1440
            or abs((s['end'] - s['start']) * 24 - c['frames']) > 1e-6):
        raise ValueError('Wake must match the approved portrait frame clock')
    if (not isinstance(r, dict) or set(r) != {'semantic_family', 'information_units', 'numeric_values', 'numeric_scale'}
            or not isinstance(r['semantic_family'], str) or not r['semantic_family'].strip()
            or type(r['information_units']) is not int or r['information_units'] < 1
            or r['numeric_values'] != [] or r['numeric_scale'] != 'not_applicable'):
        raise ValueError('Wake requires an image-led semantic request, not numeric data fabrication')
    check_descriptor(b['image'])
    result = relative(b['result_record_path'])
    if result.parts[0] != 'native-inputs' or result.suffix != '.json' or str(result) == b['image']['job_path']:
        raise ValueError('Wake result must be a distinct native-inputs JSON record')
    if 'revision' in b:
        revision = b['revision']
        if (not isinstance(revision, dict) or set(revision) != {
                'reason', 'previous_brief', 'previous_result', 'previous_media', 'project_parent'}
                or not isinstance(revision['reason'], str) or not revision['reason'].strip()):
            raise ValueError('Wake revision needs the previous work and an actual issue')
        for name in ('previous_brief', 'previous_result', 'previous_media'):
            check_descriptor(revision[name])
        parent = relative(revision['project_parent'])
        if (parent.parts[0] != 'native-projects' or len(parent.parts) != 2
                or result == Path(revision['previous_result']['job_path'])):
            raise ValueError('Wake revision requires new native project and result paths')
    return b


def _revision_inputs(root, brief):
    if 'revision' in brief:
        for name in ('previous_brief', 'previous_result', 'previous_media'):
            exact(root, brief['revision'][name])


def prepare_revision(job_dir, brief_path, *, reason):
    """Preserve completed work and prepare a new request through state.revise.

    This returns rebind inputs only. The new visual plan must pass the existing
    confirmation flow before pending_native_actions may dispatch it.
    """
    from edit.hd.tools import state
    root = Path(job_dir).resolve(strict=True)
    previous_brief = Path(brief_path).resolve(strict=True)
    previous_brief.relative_to(root)
    payload = previous_brief.read_bytes()
    brief = validate_brief(payload)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Wake revision needs an actual issue')
    job = state.load_job(root)
    if brief['job_id'] != job.job_id:
        raise ValueError('Wake revision belongs to another Job')
    completed = inspect_result(root, payload)
    token = 'wake-revision-' + uuid.uuid4().hex
    destination = path(root, 'native-inputs/' + token)
    project_parent = 'native-projects/' + token
    revised = {**brief, 'result_record_path': 'native-inputs/' + token + '/result.json',
               'revision': {'reason': reason.strip(),
                            'previous_brief': descriptor(root, previous_brief),
                            'previous_result': descriptor(root, path(root, brief['result_record_path'])),
                            'previous_media': completed['media'], 'project_parent': project_parent}}
    validate_brief(json.dumps(revised))
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / 'brief.json'
    artifacts.write_json_artifact(target, revised)
    state.revise(job, 'visual_direction', reason.strip(),
                 artifact_scope=(brief['source_binding']['segment_id'],))
    return {'action': 'rebind_native_revision', 'job_id': job.job_id, 'revision': job.revision,
            'stage': 'visual_direction', 'status': job.stages['visual_direction']['status'],
            'segment_id': brief['source_binding']['segment_id'],
            'previous_brief_path': previous_brief.relative_to(root).as_posix(),
            'brief_path': target.relative_to(root).as_posix(), 'brief_sha256': sha(target),
            'result_record_path': revised['result_record_path'], 'project_parent': project_parent,
            'revision_context': revised['revision'],
            'next': 'Bind the new brief in a new director/treatment draft and use the existing visual confirmation flow. Preserve previous files; do not dispatch native work before the new plan is authorized.'}


def validate_selected_inputs(job, director, treatment):
    """Check callable image inputs before publishing the complete proposal."""
    scenes = {(x.get('segment_id'), x.get('component_id')): x for x in treatment.get('scenes', [])}
    opening = treatment.get('skill_selection', {}).get('opening', {})
    from edit.hd.tools.visual_plan import _approved_artifact
    approved_aroll = None
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if binding.get('dependency_id') != DEPENDENCY_ID:
                continue
            key = (segment['segment_id'], cid)
            scene = scenes.get(key)
            if not scene or not isinstance(scene.get('brief_path'), str):
                raise ValueError('Selected Wake item requires an existing image brief before confirmation')
            payload = path(job.job_dir, scene['brief_path']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256'):
                raise ValueError('Selected Wake image brief differs from its binding')
            b = validate_brief(payload)
            exact(job.job_dir, b['image'])
            if approved_aroll is None:
                approved_aroll = sha(_approved_artifact(job, 'edit_structure', '06-edit-structure/edited-aroll.mp4'))
            purpose = 'opening' if key == (opening.get('segment_id'), opening.get('component_id')) else 'body'
            if (b['job_id'] != job.job_id or b['purpose'] != purpose
                    or b['source_binding'] != {'aroll_sha256': approved_aroll, 'segment_id': segment['segment_id'],
                                               'start': segment['start'], 'end': segment['end']}):
                raise ValueError('Selected Wake input belongs to another Job, clock or purpose')


def source_root(project=PROJECT):
    from prepare_sources import bundled_source_revision
    root = Path(project) / 'skill-development/vendor/lemo-wake'
    if bundled_source_revision(Path(project), root) != UPSTREAM_COMMIT:
        raise ValueError('Complete pinned native Wake source is required')
    if (root / '.git').exists():
        head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True)
        if head != UPSTREAM_COMMIT or dirty:
            raise ValueError('Native Wake source changed; do not reset or edit it')
    return root


def runtime_environment(project=PROJECT):
    """Use the existing untracked runtime area, never the vendor source tree."""
    project = Path(project).resolve(strict=True)
    models = project / 'skill-development/runtime/lemo-wake/models'
    if models.resolve() != models.absolute():
        raise ValueError('Wake model data must use the regular project runtime directory')
    from project_python import project_environment
    environment, _ = project_environment(project)
    return {**environment, 'LEMO_WAKE_MODELS': str(models)}


def _config(root, src, b, normalized=None):
    directory = Path(src).resolve(strict=True)
    text = (directory / 'config.js').read_text()
    def number(key):
        hit = re.search(r'\b' + key + r'\s*:\s*([0-9.]+)', text)
        if not hit:
            raise ValueError('Wake config is missing ' + key)
        return float(hit.group(1))
    if ((number('outW'), number('outH'), number('fps')) != (1080, 1920, 24)
            or round(number('dur') * 24) != b['composition']['frames']):
        raise ValueError('Native Wake config differs from the approved clock')
    hit = re.search(r"\bsource\s*:\s*(['\"])([^'\"]+)\1", text)
    if not hit:
        raise ValueError('Native Wake config source is missing')
    source = path(directory, hit.group(2))
    if normalized and descriptor(root, source) != normalized:
        raise ValueError('Native normalized source changed after initialization')
    return descriptor(root, source)


def _write_call(root, b, step, record):
    target = path(root, str(Path(b['result_record_path']).parent / 'calls' / (step + '-' + uuid.uuid4().hex + '.json')))
    target.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(target, record)
    return target


def initialize_project(job_dir, brief_path, *, slug, parent=None):
    """Run the original new_project program with the frozen input and public options."""
    root = Path(job_dir).resolve(strict=True)
    brief_path = Path(brief_path).resolve(strict=True)
    brief_path.relative_to(root)
    b = validate_brief(brief_path.read_bytes())
    image = exact(root, b['image'])
    _revision_inputs(root, b)
    if not isinstance(slug, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', slug):
        raise ValueError('Native project slug must be a lowercase project name')
    required_parent = b.get('revision', {}).get('project_parent')
    if required_parent and parent is not None and parent != required_parent:
        raise ValueError('Wake revision must use its new native project directory')
    destination = path(root, parent or required_parent or 'native-projects')
    src = destination / (slug + '-alive') / 'src'
    if src.parent.exists():
        raise ValueError('Native project already exists; preserve it and inspect its init record')
    destination.mkdir(parents=True, exist_ok=True)
    native = source_root() / 'skills/wake/scripts/new_project.py'
    argv = [sys.executable, str(native), str(image), slug, '--parent', str(destination),
            '--out', '1080x1920', '--fps', '24', '--dur', str(b['composition']['frames'] / 24)]
    environment = runtime_environment()
    result = subprocess.run(argv, cwd=root, env=environment, capture_output=True, text=True, timeout=120)
    record = {'schema_version': 2, 'kind': 'wake-native-call', 'step': 'init',
              'request_sha256': sha(brief_path), 'job_id': b['job_id'], 'argv': argv,
              'native_script_sha256': sha(native), 'upstream_commit': UPSTREAM_COMMIT,
              'exit_code': result.returncode, 'project_src': src.relative_to(root).as_posix(),
              'source_image': b['image'], 'environment': {'LEMO_WAKE_MODELS': environment['LEMO_WAKE_MODELS']},
              'stdout': result.stdout, 'stderr': result.stderr}
    if result.returncode == 0:
        record['normalized_source'] = _config(root, src, b)
    target = _write_call(root, b, 'init', record)
    if result.returncode:
        raise ValueError('Native initialization failed; inspect ' + str(target) + ': ' + result.stderr[-1000:])
    exact(root, b['image'])
    source_root()
    return {'project_src': str(src), 'initialization_record': str(target)}


def probe(video):
    data = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-show_streams', '-of', 'json', str(video)], text=True))['streams']
    if (len(data) != 1 or data[0].get('codec_type') != 'video'
            or data[0].get('codec_name') != 'h264' or data[0].get('pix_fmt') != 'yuv420p'
            or (data[0]['width'], data[0]['height']) != (1080, 1920)
            or data[0]['avg_frame_rate'] != '24/1'):
        raise ValueError('Native Wake output must be silent portrait 24fps H264/yuv420p')
    return {'width': 1080, 'height': 1920, 'fps': 24, 'frames': int(data[0]['nb_frames']), 'audio_streams': 0}


def project_files(root, src):
    directory = Path(src).resolve(strict=True)
    if not directory.is_relative_to(Path(root).resolve(strict=True)):
        raise ValueError('Native Wake project must be inside its Job')
    # Only original creative inputs. Native render/QA outputs are kept separately.
    files = [descriptor(root, f) for f in sorted(directory.rglob('*')) if f.is_file()
            and not set(f.relative_to(directory).parts) & {'frames', 'stills', 'node_modules'}
            and f.name not in {'render.log', 'qa_sheet.jpg', 'qa_sheet.png'}]
    director = directory.parent / 'DIRECTOR.md'
    if not director.is_file():
        raise ValueError('Complete native Wake workflow requires its DIRECTOR.md')
    return files + [descriptor(root, director)]


def capture_call(job_dir, brief_path, step, argv, project_src):
    root, brief_path = Path(job_dir).resolve(strict=True), Path(brief_path).resolve(strict=True)
    brief_path.relative_to(root)
    b = validate_brief(brief_path.read_bytes())
    exact(root, b['image'])
    _revision_inputs(root, b)
    if step not in {'render', 'encode', 'qa'}:
        raise ValueError('Use initialize_project for the original native init step')
    native = source_root() / 'skills/wake/scripts' / STEPS[step]
    if (not isinstance(argv, list) or any(not isinstance(x, str) for x in argv)
            or argv.count(str(native)) != 1 or not 1 <= argv.index(str(native)) <= 3
            or set(argv[:argv.index(str(native))]) & {'-c', '-e', '--eval'}):
        raise ValueError('Capture must execute the original native command directly')
    src = str(Path(project_src).resolve(strict=True))
    if 'revision' in b:
        destination = path(root, b['revision']['project_parent']).resolve()
        if not Path(src).is_relative_to(destination):
            raise ValueError('Wake revision must execute its new native project')
        if step == 'encode':
            output = argv[argv.index(str(native)) + 2]
            if not Path(output).is_absolute() or not Path(output).resolve().is_relative_to(destination):
                raise ValueError('Wake revision encode must preserve previous output files')
        if step == 'qa':
            if ('--json' not in argv or not Path(argv[argv.index('--json') + 1]).is_absolute()
                    or not Path(argv[argv.index('--json') + 1]).resolve().is_relative_to(destination)):
                raise ValueError('Wake revision QA must preserve previous output files')
    if step == 'render' and (argv[argv.index(str(native)) + 1:][:2] != [src, 'frames']):
        raise ValueError('Native render must use this project and single-pass frames')
    if step in {'encode', 'qa'} and argv[argv.index(str(native)) + 1] != str(Path(src) / 'frames'):
        raise ValueError('Native encode and QA must consume this project frames')
    if step == 'qa' and ('--no-loop' not in argv or '--json' not in argv or '--src' not in argv
                         or argv[argv.index('--src') + 1] != src):
        raise ValueError('Native single-pass QA must save JSON and check this project source')
    _config(root, project_src, b)
    before = project_files(root, project_src)
    environment = runtime_environment()
    result = subprocess.run(argv, cwd=root, env=environment, capture_output=True, text=True, timeout=600)
    if before != project_files(root, project_src):
        raise ValueError('Native project changed during execution; review before recapturing')
    source_root()
    record = {'schema_version': 2, 'kind': 'wake-native-call', 'request_sha256': sha(brief_path),
              'job_id': b['job_id'], 'step': step, 'argv': argv, 'native_script_sha256': sha(native),
              'upstream_commit': UPSTREAM_COMMIT, 'exit_code': result.returncode,
              'project_src': Path(src).relative_to(root).as_posix(), 'project_files': before,
              'environment': {'LEMO_WAKE_MODELS': environment['LEMO_WAKE_MODELS']},
              'stdout': result.stdout, 'stderr': result.stderr}
    target = _write_call(root, b, step, record)
    if result.returncode:
        raise ValueError('Native ' + step + ' failed; inspect ' + str(target) + ': ' + result.stderr[-1000:])
    return target


def check_result(b, request_sha, record, read):
    if any(record.get(k) != v for k, v in {'schema_version': 2, 'status': 'completed',
            'dependency_id': DEPENDENCY_ID, 'template_id': TEMPLATE_ID, 'upstream_commit': UPSTREAM_COMMIT,
            'job_id': b['job_id'], 'request_sha256': request_sha,
            'source_image_sha256': b['image']['sha256'], 'media_probe': {**b['composition'], 'audio_streams': 0}}.items()):
        raise ValueError('Native Wake result differs from its approved request or clock')
    files, calls = record.get('project_files', []), record.get('calls', [])
    if (not files or not any(f['job_path'].endswith('/index.html') for f in files)
            or not any(f['job_path'].endswith('/DIRECTOR.md') for f in files) or len(calls) != 4):
        raise ValueError('Wake requires native project source and all four actual commands')
    previous = ([b['revision'][name] for name in ('previous_brief', 'previous_result', 'previous_media')]
                if 'revision' in b else [])
    for d in [b['image'], record['media'], record['native_qa'], *calls, *previous]:
        check_descriptor(d)
        content = read(d['job_path'])
        if len(content) != d['byte_count'] or hashlib.sha256(content).hexdigest() != d['sha256']:
            raise ValueError('Frozen Wake evidence differs: ' + d['job_path'])
    qa = json.loads(read(record['native_qa']['job_path']))
    if not isinstance(qa, list) or not qa or any(not isinstance(x, dict) or x.get('level') == 'FAIL' for x in qa):
        raise ValueError('Original Wake QA is missing or contains failure')
    steps = {}
    for d in calls:
        call = json.loads(read(d['job_path']))
        step = call.get('step')
        native = source_root() / 'skills/wake/scripts' / STEPS.get(step, 'invalid')
        if (step in steps or step not in STEPS or call.get('kind') != 'wake-native-call'
                or call.get('exit_code') != 0 or call.get('job_id') != b['job_id']
                or call.get('request_sha256') != request_sha or call.get('upstream_commit') != UPSTREAM_COMMIT
                or call.get('schema_version') != 2 or call.get('native_script_sha256') != sha(native)
                or (step != 'init' and call.get('project_files') != files)
                or sum(arg.endswith('/lemo-wake/skills/wake/scripts/' + STEPS[step])
                       for arg in call.get('argv', [])) != 1):
            raise ValueError('Wake command evidence is incomplete or belongs to another execution')
        steps[step] = call
    if set(steps) != set(STEPS) or '--no-loop' not in steps['qa']['argv']:
        raise ValueError('Wake single-pass native workflow did not finish')
    sources = {call.get('project_src') for call in steps.values()}
    if len(sources) != 1:
        raise ValueError('Native commands belong to different Wake projects')
    src = sources.pop()
    relative(src)
    for d in files:
        # new_project.py creates this optional stylesheet empty. Freeze its original bytes.
        check_descriptor(d, project_src=src)
        content = read(d['job_path'])
        if len(content) != d['byte_count'] or hashlib.sha256(content).hexdigest() != d['sha256']:
            raise ValueError('Frozen Wake evidence differs: ' + d['job_path'])
    if 'revision' in b and not Path(src).is_relative_to(Path(b['revision']['project_parent'])):
        raise ValueError('Wake revised result must come from its new native project')
    if 'revision' in b and any(not Path(record[name]['job_path']).is_relative_to(
            Path(b['revision']['project_parent'])) for name in ('media', 'native_qa')):
        raise ValueError('Wake revised output must use its new native project directory')
    for step, call in steps.items():
        if step == 'init':
            continue
        argv = call['argv']
        index = next(i for i, arg in enumerate(argv) if arg.endswith('/lemo-wake/skills/wake/scripts/' + STEPS[step]))
        expected = src if step == 'render' else src + '/frames'
        if not argv[index + 1].endswith('/' + expected) or (step == 'render' and argv[index + 2] != 'frames'):
            raise ValueError('Native command does not consume its recorded project')
    init = steps['init']
    argv = init['argv']
    script_index = next(i for i, arg in enumerate(argv) if arg.endswith('/lemo-wake/skills/wake/scripts/new_project.py'))
    if (init.get('source_image') != b['image'] or not argv[script_index + 1].endswith('/' + b['image']['job_path'])
            or '--fps' not in argv or argv[argv.index('--fps') + 1] != '24'
            or '--out' not in argv or argv[argv.index('--out') + 1] != '1080x1920'):
        raise ValueError('Native initialization did not consume the approved source and output request')
    normalized = init.get('normalized_source')
    check_descriptor(normalized)
    if normalized not in files or not normalized['job_path'].startswith(src + '/assets/source.'):
        raise ValueError('Native initialization source is not the frozen project source')
    for call in steps.values():
        environment = call.get('environment')
        if (environment != init.get('environment') or not isinstance(environment, dict)
                or set(environment) != {'LEMO_WAKE_MODELS'}
                or not environment['LEMO_WAKE_MODELS'].endswith('/skill-development/runtime/lemo-wake/models')):
            raise ValueError('Native Wake commands did not use the isolated model directory')
    if src + '/index.html' not in {f['job_path'] for f in files}:
        raise ValueError('Rendered Wake project entry is not frozen')
    qa_argv, enc_argv = steps['qa']['argv'], steps['encode']['argv']
    if ('--src' not in qa_argv or not qa_argv[qa_argv.index('--src') + 1].endswith('/' + src)
            or '--json' not in qa_argv or not qa_argv[qa_argv.index('--json') + 1].endswith('/' + record['native_qa']['job_path'])):
        raise ValueError('Native QA is not tied to the saved result and source')
    video = record['media']['job_path']
    index = next(i for i, arg in enumerate(enc_argv) if arg.endswith('/lemo-wake/skills/wake/scripts/encode.py'))
    prefix = enc_argv[index + 2]
    if not (prefix + '.mp4').endswith('/' + video):
        raise ValueError('Native encode command does not produce this video')
    if '--encode' not in qa_argv or qa_argv[qa_argv.index('--encode') + 1] != prefix + '.encode.json':
        raise ValueError('Native QA did not inspect the encoded output')
    return record


def _read_result(job_dir, payload, data):
    b = validate_brief(payload)
    root = Path(job_dir).resolve(strict=True)
    exact(root, b['image'])
    _revision_inputs(root, b)
    record = json.loads(data)
    checked = check_result(b, hashlib.sha256(payload).hexdigest(), record, lambda name: path(root, name).read_bytes())
    if probe(exact(root, checked['media'])) != checked['media_probe']:
        raise ValueError('Native Wake output differs from its recorded probe')
    src = root / next(f['job_path'] for f in checked['project_files'] if f['job_path'].endswith('/index.html'))
    init = next(json.loads(path(root, d['job_path']).read_bytes()) for d in checked['calls']
                if json.loads(path(root, d['job_path']).read_bytes())['step'] == 'init')
    _config(root, src.parent, b, init['normalized_source'])
    return checked


def inspect_result(job_dir, payload, *, record_bytes=None):
    """Inspect unapproved native work; never use this entry to produce a component."""
    b = validate_brief(payload)
    return _read_result(job_dir, payload, record_bytes if record_bytes is not None else path(job_dir, b['result_record_path']).read_bytes())


def load_result(job_dir, payload, *, expected_record):
    """Production consumes the exact result the host reviewed and froze."""
    b = validate_brief(payload)
    if (not isinstance(expected_record, dict) or set(expected_record) != {'path', 'sha256', 'bytes'}
            or expected_record['path'] != b['result_record_path']):
        raise ValueError('Approved Wake result descriptor is required')
    data = path(job_dir, expected_record['path']).read_bytes()
    if len(data) != expected_record['bytes'] or hashlib.sha256(data).hexdigest() != expected_record['sha256']:
        raise ValueError('Wake result differs from the reviewed version')
    return _read_result(job_dir, payload, data)


def publish_completed(job_dir, brief_path, project_src, video, native_qa, calls):
    root, payload = Path(job_dir).resolve(strict=True), Path(brief_path).read_bytes()
    b = validate_brief(payload)
    record = {'schema_version': 2, 'status': 'completed', 'dependency_id': DEPENDENCY_ID,
              'template_id': TEMPLATE_ID, 'upstream_commit': UPSTREAM_COMMIT, 'job_id': b['job_id'],
              'request_sha256': hashlib.sha256(payload).hexdigest(), 'source_image_sha256': b['image']['sha256'],
              'media': descriptor(root, video), 'media_probe': probe(video),
              'project_files': project_files(root, project_src), 'native_qa': descriptor(root, native_qa),
              'calls': [descriptor(root, item) for item in calls]}
    check_result(b, hashlib.sha256(payload).hexdigest(), record, lambda name: path(root, name).read_bytes())
    target = path(root, b['result_record_path'])
    if target.exists() and json.loads(target.read_bytes()) != record:
        raise ValueError('Wake completion already exists; preserve it and review the changed result')
    target.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(target, record)
    return target


def native_task(job, recipe, component, brief_path):
    payload = Path(brief_path).read_bytes()
    b = validate_brief(payload)
    exact(job.job_dir, b['image'])
    _revision_inputs(job.job_dir, b)
    if sha(brief_path) != component['brief_sha256'] or b['job_id'] != job.job_id:
        raise ValueError('Wake handoff differs from the confirmed component')
    from edit.hd.tools.motion_capabilities import _approved_speech
    spoken = [word for word in _approved_speech(job.job_dir)
              if word['start'] < b['source_binding']['end'] and word['end'] > b['source_binding']['start']]
    if not spoken:
        raise ValueError('Wake native task needs the current approved spoken clause')
    return {'action': 'execute_native_skill', 'dependency_id': DEPENDENCY_ID, 'template_id': TEMPLATE_ID,
            'skill_path': str(source_root() / NATIVE_ENTRY), 'job_dir': str(job.job_dir),
            'brief_path': str(brief_path), 'brief_sha256': component['brief_sha256'],
            'source_image': str(path(job.job_dir, b['image']['job_path'])),
            'working_directory': str(job.job_dir),
            'project_parent': b.get('revision', {}).get('project_parent', 'native-projects'),
            **({'revision_context': b['revision'],
                'output_directory': str(path(job.job_dir, b['revision']['project_parent']))}
               if 'revision' in b else {}),
            'environment': {'LEMO_WAKE_MODELS': runtime_environment()['LEMO_WAKE_MODELS']},
            'history_path': str(Path(job.job_dir) / 'lemo-wake-history.jsonl'),
            'segment_id': recipe['segment_id'], 'component_id': component['component_id'],
            'requirements': {**b['composition'], 'semantic_goal': b['semantic_goal'], 'purpose': b['purpose'],
                             'transcript': ''.join(word['text'] for word in spoken),
                             'word_anchors': [{'text': word['text'],
                                 'start': max(0, word['start'] - b['source_binding']['start']),
                                 'end': min(b['source_binding']['end'], word['end']) - b['source_binding']['start']} for word in spoken],
                             'silent': True, 'single_pass': True},
            'result_record_path': b['result_record_path'],
            'next': 'Read and execute the complete native Skill in a native subtask. Use initialize_project with project_parent to record the original new_project call and source derivation. When output_directory is provided, save encoded media and QA there. The native Skill plans the complete scene, layers and motion. single_pass means non-looping playback; it does not limit render or QA iterations. Capture original render/encode/qa (--no-loop --json) commands with this bridge, inspect frames and motion, then publish. Preserve previous revision work, the approved brief, vendor code and user movie.'}


def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    source_root(project_root)
    launcher = Path(python_executable).resolve(strict=True)
    entry_sha = sha(SKILL / ENTRY)

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary
        payload = brief_loader(job, recipe, component)
        b = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan['segments'] if s['segment_id'] == recipe['segment_id'])
        arroll = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment['shot_recipe'] or b['job_id'] != job.job_id
                or b['source_binding'] != {'aroll_sha256': arroll['sha256'], 'segment_id': segment['segment_id'], 'start': segment['start'], 'end': segment['end']}
                or b['template_request'] != json.loads(json.dumps(component['invocation_record']['template_request']))
                or component['template_id'] != TEMPLATE_ID or component['source_sha256'] != entry_sha
                or component['render_window']['start_frame'] != 0
                or component['render_window']['end_frame'] != b['composition']['frames']
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': False}):
            raise ValueError('Wake differs from the approved Job, request, source or render clock')
        exact(job.job_dir, b['image'])
        source_root(project_root)
        return payload

    def media_loader(job, recipe, component, payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected = native_result_descriptor(job, recipe['segment_id'], component['component_id'], hashlib.sha256(payload).hexdigest())
        b, result = validate_brief(payload), load_result(job.job_dir, payload, expected_record=expected)
        descriptors = [b['image'], {'job_path': expected['path'], 'sha256': expected['sha256'], 'byte_count': expected['bytes']},
                       result['media'], result['native_qa'], *result['project_files'], *result['calls']]
        if 'revision' in b:
            descriptors.extend(b['revision'][name] for name in ('previous_brief', 'previous_result', 'previous_media'))
        distinct = {d['job_path']: d for d in descriptors}
        return tuple(ReferenceProcessMedia('wake-' + hashlib.sha256(d['job_path'].encode()).hexdigest()[:32], d['job_path'], d['sha256']) for d in distinct.values())

    return ReferenceProcessAdapter(adapter_id='wake-native-v1', dependency_id=DEPENDENCY_ID,
        approved_executor='reference_adapter', dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer='HTMLCanvas',
        renderer_version=UPSTREAM_COMMIT, artifact_media_type='video', launcher=launcher,
        launcher_sha256=sha(launcher), self_contained_wrapper=True, brief_loader=guarded_loader,
        media_loader=media_loader, timeout_seconds=120,
        argv_template=('{launcher}', '{entrypoint}', '--skill-root', str(SKILL), '--brief', '{brief_path}',
                       '--media-manifest', '{media_manifest_fd}', '--output', '{output_path}'))


def create_binding(adapter, brief_bytes, reference_sample):
    b = validate_brief(brief_bytes)
    digest = hashlib.sha256(brief_bytes).hexdigest()
    return {'producer_type': 'dependency', 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'primary_renderer': 'HTMLCanvas', 'renderer_version': UPSTREAM_COMMIT,
            'template_origin': 'custom_fallback', 'template_id': TEMPLATE_ID, 'template_version': VERSION,
            'adaptation_level': 'structural', 'verification_id': hashlib.sha256((adapter.entrypoint_sha256 + digest).encode()).hexdigest(),
            'source_entrypoint': ENTRY, 'source_sha256': adapter.entrypoint_sha256, 'sample_sha256': sha(reference_sample),
            'semantic_families': [b['template_request']['semantic_family']],
            'capacity': {'min_units': 1, 'max_units': b['template_request']['information_units']},
            'brief_sha256': digest,
            'invocation_record': {'argv': [str(adapter.launcher), ENTRY], 'status': 'planned', 'exit_code': None,
                                  'template_request': b['template_request']}}


def create_artifact_probe(*, ffprobe_executable):
    from data_rollup_adapter import create_artifact_probe as factory
    return factory(ffprobe_executable=ffprobe_executable)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skill-root', type=Path)
    p.add_argument('--brief', type=Path)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--project-root', type=Path)
    p.add_argument('--job-dir', type=Path)
    p.add_argument('--capture', choices=('render', 'encode', 'qa'))
    p.add_argument('--initialize', action='store_true')
    p.add_argument('--revise', action='store_true')
    p.add_argument('--revision-reason')
    p.add_argument('--slug')
    p.add_argument('--parent')
    p.add_argument('--argv-json')
    p.add_argument('--project-src', type=Path)
    p.add_argument('--publish', action='store_true')
    p.add_argument('--video', type=Path)
    p.add_argument('--native-qa', type=Path)
    p.add_argument('--calls', nargs='*', type=Path)
    p.add_argument('--media-manifest', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.probe:
        source_root(a.project_root)
        from ensure_visual_broll_skills import prepare_wake_runtime
        prepare_wake_runtime(a.project_root)
        print(json.dumps({'schema_version': 1, 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'adapter_identity': {'adapter_type': 'ReferenceProcessAdapter',
            'approved_executor': 'reference_adapter', 'primary_renderer': 'HTMLCanvas'}}))
        return
    if a.brief is None:
        p.error('--brief is required for native execution and reuse')
    if a.revise:
        print(json.dumps(prepare_revision(a.job_dir, a.brief, reason=a.revision_reason)))
    elif a.initialize:
        print(json.dumps(initialize_project(a.job_dir, a.brief, slug=a.slug, parent=a.parent)))
    elif a.capture:
        print(capture_call(a.job_dir, a.brief, a.capture, json.loads(a.argv_json), a.project_src))
    elif a.publish:
        print(publish_completed(a.job_dir, a.brief, a.project_src, a.video, a.native_qa, a.calls))
    else:
        payload = a.brief.read_bytes()
        b = validate_brief(payload)
        manifest = json.loads(a.media_manifest.read_bytes())
        if manifest['brief_sha256'] != hashlib.sha256(payload).hexdigest():
            raise ValueError('Frozen Wake request differs')
        files = {x['media_ref']: x for x in manifest['media']}
        cached = {}
        def read(name):
            if name in cached:
                return cached[name]
            item = files['wake-' + hashlib.sha256(name.encode()).hexdigest()[:32]]
            data = Path('/dev/fd/' + str(item['fd'])).read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256'] or len(data) != item['byte_length']:
                raise ValueError('Frozen Wake descriptor differs: ' + name)
            cached[name] = data
            return data
        record = json.loads(read(b['result_record_path']))
        check_result(b, hashlib.sha256(payload).hexdigest(), record, read)
        a.output.write_bytes(read(record['media']['job_path']))
        print(json.dumps({'dependency_id': DEPENDENCY_ID, 'template_id': TEMPLATE_ID,
                          'upstream_commit': UPSTREAM_COMMIT, 'native_result_sha256': sha(a.output)}))

if __name__ == '__main__':
    main()

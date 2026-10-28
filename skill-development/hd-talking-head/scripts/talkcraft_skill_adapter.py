"""Invoke the complete pinned TalkCraft Skill and consume its reviewed native output.

The host passes content, materials and delivery constraints. The native Skill
owns SHOTBOOK, composition, card configuration and render_shots.mjs execution.
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

ENTRY = 'scripts/talkcraft_skill_adapter.py'
DEPENDENCY_ID = 'video-talkcraft'
VERSION = '1.0.0'
UPSTREAM_COMMIT = 'ccb8a571f4bd620b5588bef4b264b5120f5042fc'
SOURCE_RECORD = 'references/talkcraft-native-source.json'
SOURCE_RECORD_SHA256 = 'b2faf3b368dbbbbfdd78176c69acc983085d22cd752e9f57c1b3b5f8143731ce'
SOURCE_ROOT = 'edit/hd/integrations/talkcraft/upstream'
NATIVE_RENDER = 'scripts/render_shots.mjs'


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or Path(value).is_absolute()
            or '..' in Path(value).parts or Path(value).as_posix() != value):
        raise ValueError('TalkCraft requires a canonical Job-relative path')
    return Path(value)


def path(root, value):
    root = Path(root).resolve(strict=True)
    target = root / relative(value)
    if not target.resolve().is_relative_to(root):
        raise ValueError('TalkCraft path escapes this Job')
    return target


def descriptor(root, target):
    target = Path(target).resolve(strict=True)
    return {'job_path': target.relative_to(Path(root).resolve(strict=True)).as_posix(),
            'sha256': sha(target), 'byte_count': target.stat().st_size}


def exact(root, record):
    if (not isinstance(record, dict) or set(record) != {'job_path', 'sha256', 'byte_count'}
            or not re.fullmatch('[a-f0-9]{64}', str(record['sha256']))
            or type(record['byte_count']) is not int or record['byte_count'] < 1):
        raise ValueError('Invalid TalkCraft file descriptor')
    target = path(root, record['job_path'])
    if target.stat().st_size != record['byte_count'] or sha(target) != record['sha256']:
        raise ValueError('TalkCraft frozen input or evidence changed: ' + record['job_path'])
    return target


def source_root(project=PROJECT):
    project = Path(project).resolve(strict=True)
    record_path = project / 'skill-development/hd-talking-head' / SOURCE_RECORD
    if sha(record_path) != SOURCE_RECORD_SHA256:
        raise ValueError('TalkCraft native source identity record changed')
    record = json.loads(record_path.read_bytes())
    if record['commit'] != UPSTREAM_COMMIT or record['source_root'] != SOURCE_ROOT:
        raise ValueError('TalkCraft native source revision changed')
    root = project / SOURCE_ROOT
    for name, digest in record['files'].items():
        source = root / relative(name)
        if source.is_symlink() or not source.is_file() or sha(source) != digest:
            raise ValueError('Complete pinned TalkCraft source is required: ' + name)
    return root


def load_card_catalog(project=PROJECT):
    """Native recipe identities and roles; one Skill/channel, no derived animation."""
    root = source_root(project)
    roles = {'字幕花字': 'overlay', '强调标注': 'annotation', '转场结构': 'transition', '运镜': 'camera'}
    result = []
    for source in sorted((root / 'template/cards').glob('*.tsx')):
        guide = root / 'references/cards' / (source.stem + '.md')
        header = guide.read_text(encoding='utf-8').split('---', 2)[1]
        metadata = dict(line.split(':', 1) for line in header.splitlines() if ':' in line)
        metadata = {key.strip(): value.strip() for key, value in metadata.items()}
        result.append({'card_id': source.stem, 'title': metadata['标题'], 'summary': metadata['一句话'],
                       'category': metadata['类别'], 'native_role': roles.get(metadata['类别'], 'scene'),
                       'source': str(source), 'instructions': str(guide)})
    if len(result) != 108:
        raise ValueError('TalkCraft requires all 108 original recipe cards')
    return result


def validate_brief(payload):
    brief = json.loads(payload)
    required = {'schema_version', 'job_id', 'source_binding', 'composition', 'template_request',
                'card_id', 'semantic_goal', 'transcript', 'word_anchors', 'speech', 'materials',
                'authorization', 'project_directory', 'result_record_path'}
    if (not isinstance(brief, dict) or set(brief) != required or brief['schema_version'] != 1
            or any(not isinstance(brief[k], str) or not brief[k].strip()
                   for k in ('job_id', 'card_id', 'semantic_goal', 'transcript'))):
        raise ValueError('Invalid TalkCraft native task brief')
    validate_source_binding(brief['source_binding'], 'Invalid TalkCraft source clock')
    if not re.fullmatch('[a-z][a-z0-9-]{0,63}', brief['card_id']):
        raise ValueError('Invalid native TalkCraft recipe identity')
    composition = brief['composition']
    if (not isinstance(composition, dict) or set(composition) != {'width', 'height', 'fps', 'frames'}
            or (composition['width'], composition['height'], composition['fps']) != (1080, 1920, 24)
            or type(composition['frames']) is not int or composition['frames'] < 1
            or abs((brief['source_binding']['end'] - brief['source_binding']['start']) * 24 - composition['frames']) > 1e-6):
        raise ValueError('TalkCraft requires the exact approved portrait 24fps clock')
    request = brief['template_request']
    if (not isinstance(request, dict) or set(request) != {'semantic_family', 'information_units', 'numeric_values', 'numeric_scale'}
            or not isinstance(request['semantic_family'], str) or not request['semantic_family'].strip()
            or type(request['information_units']) is not int or request['information_units'] < 1
            or not isinstance(request['numeric_values'], list)
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in request['numeric_values'])
            or request['numeric_scale'] not in ({'linear', 'log'} if request['numeric_values'] else {'not_applicable'})):
        raise ValueError('Invalid TalkCraft semantic or numeric input')
    if (not isinstance(brief['materials'], list) or not isinstance(brief['authorization'], dict)
            or not isinstance(brief['word_anchors'], list) or not brief['word_anchors']):
        raise ValueError('TalkCraft requires real materials, resource authorization and word times')
    duration = composition['frames'] / 24
    for word in brief['word_anchors']:
        if (not isinstance(word, dict) or set(word) != {'text', 'start', 'end'}
                or not isinstance(word['text'], str) or not word['text']
                or any(type(word[k]) not in (int, float) or not math.isfinite(word[k]) for k in ('start', 'end'))
                or not 0 <= word['start'] < word['end'] <= duration):
            raise ValueError('TalkCraft word anchors must use this scene local clock')
    if relative(brief['project_directory']).parts[0] != 'native-projects':
        raise ValueError('TalkCraft native project must be separate from user inputs')
    result = relative(brief['result_record_path'])
    if result.parts[0] != 'native-inputs' or result.suffix != '.json':
        raise ValueError('TalkCraft result must be a native-inputs JSON record')
    return brief


def _inputs(root, brief):
    for record in [brief['speech'], *brief['materials']]:
        exact(root, record)
    speech = path(root, brief['speech']['job_path'])
    data = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', str(speech)], text=True))
    if (len(data['streams']) != 1 or data['streams'][0].get('codec_type') != 'audio'
            or abs(float(data['format']['duration']) - brief['composition']['frames'] / 24) > 1 / 24):
        raise ValueError('TalkCraft speech must be this scene audio clip on the local approved clock')


def validate_selected_inputs(job, director, treatment):
    """Check selected real inputs before confirmation, without producing media."""
    from edit.hd.tools.visual_plan import _approved_artifact
    scenes = {(scene.get('segment_id'), scene.get('component_id')): scene
              for scene in treatment.get('scenes', [])}
    arroll_sha = None
    for segment in director.get('segments', []):
        for cid, binding in segment.get('bindings', {}).items():
            if binding.get('dependency_id') != DEPENDENCY_ID:
                continue
            scene = scenes.get((segment['segment_id'], cid), {})
            if not isinstance(scene.get('brief_path'), str):
                raise ValueError('TalkCraft selected scene requires its existing native task brief')
            payload = path(job.job_dir, scene['brief_path']).read_bytes()
            brief = validate_brief(payload)
            if arroll_sha is None:
                arroll_sha = sha(_approved_artifact(job, 'edit_structure', '06-edit-structure/edited-aroll.mp4'))
            if (hashlib.sha256(payload).hexdigest() != binding.get('brief_sha256')
                    or brief['job_id'] != job.job_id
                    or brief['source_binding'] != {'aroll_sha256': arroll_sha, 'segment_id': segment['segment_id'],
                                                   'start': segment['start'], 'end': segment['end']}
                    or binding.get('template_id') != DEPENDENCY_ID + '/' + brief['card_id']):
                raise ValueError('TalkCraft selected inputs differ from this approved source, recipe or clock')
            _inputs(job.job_dir, brief)


def native_task(job, recipe, component, brief_path):
    brief_path = Path(brief_path)
    brief = validate_brief(brief_path.read_bytes())
    root = source_root()
    from prepare_talkcraft_native import check as check_runtime
    runtime = check_runtime(PROJECT)
    if brief['card_id'] not in {row['card_id'] for row in load_card_catalog()}:
        raise ValueError('Unknown native TalkCraft recipe')
    if brief['job_id'] != job.job_id or sha(brief_path) != component['brief_sha256']:
        raise ValueError('TalkCraft native task differs from the confirmed binding')
    _inputs(job.job_dir, brief)
    return {'action': 'execute_native_skill', 'dependency_id': DEPENDENCY_ID,
            'template_id': DEPENDENCY_ID + '/' + brief['card_id'], 'skill_path': str(root / 'SKILL.md'),
            'recipe_path': str(root / 'references/cards' / (brief['card_id'] + '.md')),
            'job_dir': str(job.job_dir), 'brief_path': str(brief_path), 'brief_sha256': component['brief_sha256'],
            'project_directory': str(path(job.job_dir, brief['project_directory'])),
            'runtime': runtime,
            'segment_id': recipe['segment_id'], 'component_id': component['component_id'],
            'requirements': {**brief['composition'], 'silent': True,
                'semantic_goal': brief['semantic_goal'], 'transcript': brief['transcript'],
                'word_anchors': brief['word_anchors'], 'authorization': brief['authorization']},
            'speech': str(path(job.job_dir, brief['speech']['job_path'])),
            'speech_window': {'start': 0, 'end': brief['composition']['frames'] / 24},
            'source_binding': brief['source_binding'],
            'materials': [str(path(job.job_dir, record['job_path'])) for record in brief['materials']],
            'result_record_path': brief['result_record_path'],
            'next': 'Read the complete native Skill and original recipe. The native Skill owns SHOTBOOK, composition, card CONFIG, scene code and QA. Link the project node_modules to runtime.node_modules and pass runtime.browser to the original renderer. Use the approved voice and word times; do not re-edit speech or create new voice, subtitles or paid assets. Keep the pinned Skill files unchanged. Author only the Job native project, use its original render_shots.mjs through capture_render, inspect real motion, then publish_completed. This action is pending work, not a completed result.'}


def probe(video):
    streams = json.loads(subprocess.check_output([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
        '-show_streams', '-of', 'json', str(video)], text=True))['streams']
    if (len(streams) != 1 or streams[0].get('codec_name') != 'h264'
            or streams[0].get('pix_fmt') != 'yuv420p' or streams[0].get('avg_frame_rate') != '24/1'
            or (streams[0].get('width'), streams[0].get('height')) != (1080, 1920)):
        raise ValueError('TalkCraft native output must be silent portrait H264 24fps')
    return {'width': 1080, 'height': 1920, 'fps': 24, 'frames': int(streams[0]['nb_frames'])}


def project_files(root, directory):
    directory = Path(directory).resolve(strict=True)
    directory.relative_to(Path(root).resolve(strict=True))
    files = [descriptor(root, item) for item in sorted(directory.rglob('*')) if item.is_file()
             and not set(item.relative_to(directory).parts) & {'node_modules', 'out', '.git', '.cache'}]
    if not any(item['job_path'].endswith('/SHOTBOOK.md') for item in files):
        raise ValueError('TalkCraft native planning must include SHOTBOOK.md')
    return files


def capture_render(job_dir, brief_path, argv):
    root = Path(job_dir).resolve(strict=True)
    brief_path = Path(brief_path).resolve(strict=True)
    brief_path.relative_to(root)
    brief = validate_brief(brief_path.read_bytes())
    _inputs(root, brief)
    native = source_root() / NATIVE_RENDER
    directory = path(root, brief['project_directory'])
    from prepare_talkcraft_native import check as check_runtime
    runtime = check_runtime(PROJECT)
    modules = directory / 'remotion/node_modules'
    if modules.resolve(strict=True) != Path(runtime['node_modules']).resolve(strict=True):
        raise ValueError('Native TalkCraft project must use the prepared original locked dependencies')
    renderer_package = modules / '@remotion/renderer/package.json'
    renderer_bytes = renderer_package.read_bytes()
    renderer_version = json.loads(renderer_bytes)['version']
    if (not isinstance(argv, list) or len(argv) < 2 or argv[1] != str(native)
            or not Path(argv[0]).is_absolute() or Path(argv[0]).name != 'node'
            or '--concat' not in argv or any(flag in argv for flag in ('--audio', '--mux', '--seg-audio'))):
        raise ValueError('Capture must invoke original native render_shots.mjs directly, video only')
    if '--all' not in argv or any(flag in argv for flag in ('--changed', '--only')):
        raise ValueError('Native TalkCraft capture requires --all; cached segments are not current source evidence')
    segment_arg = argv[argv.index('--seg-dir') + 1] if '--seg-dir' in argv else 'out/segments'
    segments = Path(segment_arg)
    segments = segments if segments.is_absolute() else directory / 'remotion' / segments
    if not segments.resolve().is_relative_to((directory / 'remotion').resolve()):
        raise ValueError('TalkCraft segment cache must belong to the current native project')
    output = Path(argv[argv.index('--concat') + 1])
    output = output if output.is_absolute() else directory / 'remotion' / output
    if not output.resolve().is_relative_to(directory.resolve()):
        raise ValueError('TalkCraft render must preserve previous projects and output')
    before = project_files(root, directory)
    record_path = path(root, str(Path(brief['result_record_path']).parent / 'render-call.json'))
    if record_path.exists() or output.exists():
        raise ValueError('TalkCraft render evidence/output already exists; use a new revision directory')
    result = subprocess.run(argv, cwd=directory / 'remotion', capture_output=True, text=True, timeout=600)
    if before != project_files(root, directory):
        raise ValueError('TalkCraft project source changed during native rendering')
    if renderer_package.read_bytes() != renderer_bytes:
        raise ValueError('TalkCraft native dependencies changed during rendering')
    record_path.parent.mkdir(parents=True, exist_ok=True)
    package_snapshot = record_path.parent / 'renderer-package.json'
    if package_snapshot.exists():
        raise ValueError('TalkCraft renderer identity already exists; preserve this native request')
    package_snapshot.write_bytes(renderer_bytes)
    record = {'schema_version': 1, 'request_sha256': sha(brief_path), 'upstream_commit': UPSTREAM_COMMIT,
              'native_script_sha256': sha(native), 'argv': argv, 'working_directory': directory.relative_to(root).as_posix() + '/remotion',
              'project_files': before, 'output': output.relative_to(root).as_posix(),
              'renderer_version': renderer_version, 'renderer_package': descriptor(root, package_snapshot),
              'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    record_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json_artifact(record_path, record)
    if result.returncode:
        raise ValueError('Native TalkCraft render failed: ' + result.stderr[-1500:])
    if probe(output) != brief['composition']:
        raise ValueError('TalkCraft native render differs from its approved clock')
    source_root()
    return record_path


def publish_completed(job_dir, brief_path, call_path, *, qa_note):
    root = Path(job_dir).resolve(strict=True)
    payload = Path(brief_path).read_bytes()
    brief = validate_brief(payload)
    if not isinstance(qa_note, str) or not qa_note.strip():
        raise ValueError('TalkCraft requires actual motion and content QA')
    call = json.loads(Path(call_path).read_bytes())
    if (call['exit_code'] != 0 or call['request_sha256'] != hashlib.sha256(payload).hexdigest()
            or call['upstream_commit'] != UPSTREAM_COMMIT
            or call['native_script_sha256'] != sha(source_root() / NATIVE_RENDER)):
        raise ValueError('TalkCraft native execution is missing or belongs to another request')
    if json.loads(exact(root, call['renderer_package']).read_bytes())['version'] != call['renderer_version']:
        raise ValueError('TalkCraft native renderer identity differs from its actual package')
    for item in call['project_files']:
        exact(root, item)
    video = path(root, call['output'])
    if probe(video) != brief['composition']:
        raise ValueError('TalkCraft output differs from the approved clock')
    lint_script = source_root() / 'scripts/card_lint.py'
    lint = subprocess.run([sys.executable, str(lint_script),
        str(path(root, brief['project_directory']) / 'remotion/src'), brief['card_id']],
        check=True, capture_output=True, text=True, timeout=30)
    result = {'schema_version': 1, 'status': 'completed', 'dependency_id': DEPENDENCY_ID,
              'job_id': brief['job_id'], 'card_id': brief['card_id'], 'upstream_commit': UPSTREAM_COMMIT,
              'request_sha256': hashlib.sha256(payload).hexdigest(), 'media': descriptor(root, video),
              'renderer_version': call['renderer_version'],
              'media_probe': probe(video), 'render_call': descriptor(root, call_path), 'qa_note': qa_note,
              'native_card_lint': {'script_sha256': sha(lint_script), 'exit_code': lint.returncode, 'stdout': lint.stdout}}
    target = path(root, brief['result_record_path'])
    if target.exists():
        raise ValueError('TalkCraft completed result exists; preserve it and use a new revision')
    artifacts.write_json_artifact(target, result)
    return target


def inspect_result(job_dir, payload, *, record_bytes=None):
    brief = validate_brief(payload)
    _inputs(job_dir, brief)
    source_root()
    data = record_bytes if record_bytes is not None else path(job_dir, brief['result_record_path']).read_bytes()
    result = json.loads(data)
    if any(result.get(key) != value for key, value in {'schema_version': 1, 'status': 'completed',
            'dependency_id': DEPENDENCY_ID, 'job_id': brief['job_id'], 'card_id': brief['card_id'],
            'upstream_commit': UPSTREAM_COMMIT, 'request_sha256': hashlib.sha256(payload).hexdigest(),
            'media_probe': brief['composition']}.items()):
        raise ValueError('TalkCraft native result differs from its request')
    call = json.loads(exact(job_dir, result['render_call']).read_bytes())
    if (json.loads(exact(job_dir, call['renderer_package']).read_bytes())['version'] != call['renderer_version']
            or result['renderer_version'] != call['renderer_version']):
        raise ValueError('TalkCraft native result has a different actual renderer identity')
    if (result['native_card_lint']['script_sha256'] != sha(source_root() / 'scripts/card_lint.py')
            or result['native_card_lint']['exit_code'] != 0):
        raise ValueError('TalkCraft native card fidelity check is missing')
    if (call['request_sha256'] != result['request_sha256'] or call['exit_code'] != 0
            or call['upstream_commit'] != UPSTREAM_COMMIT
            or call['native_script_sha256'] != sha(source_root() / NATIVE_RENDER)
            or call['output'] != result['media']['job_path']):
        raise ValueError('TalkCraft result has no matching native render call')
    for item in call['project_files']:
        exact(job_dir, item)
    if probe(exact(job_dir, result['media'])) != brief['composition']:
        raise ValueError('TalkCraft media changed')
    return result


def load_result(job_dir, payload, *, expected_record, expected_renderer_version):
    brief = validate_brief(payload)
    if (not isinstance(expected_record, dict) or set(expected_record) != {'path', 'sha256', 'bytes'}
            or expected_record['path'] != brief['result_record_path']):
        raise ValueError('Approved TalkCraft result descriptor is required')
    data = path(job_dir, expected_record['path']).read_bytes()
    if len(data) != expected_record['bytes'] or hashlib.sha256(data).hexdigest() != expected_record['sha256']:
        raise ValueError('TalkCraft result differs from the reviewed version')
    result = inspect_result(job_dir, payload, record_bytes=data)
    if result['renderer_version'] != expected_renderer_version:
        raise ValueError('TalkCraft native renderer differs from the frozen component')
    return result


def create_adapter(project_root, python_executable, brief_loader, *, renderer_version=None):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter, ReferenceProcessMedia
    requested = Path(project_root).absolute()
    project = requested.resolve(strict=True)
    if project != requested:
        raise ValueError('TalkCraft project root must be canonical and nonsymlinked')
    source_root(project)
    launcher = Path(python_executable).resolve(strict=True)
    entry_sha = sha(SKILL / ENTRY)
    from prepare_talkcraft_native import check as check_runtime
    runtime = check_runtime(project)
    renderer_version = renderer_version or runtime['renderer_version']

    def guarded_loader(job, recipe, component):
        from edit.hd.tools import visual_canary
        payload = brief_loader(job, recipe, component)
        brief = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(s for s in plan['segments'] if s['segment_id'] == recipe['segment_id'])
        arroll = visual_canary.approved_aroll_record(job, plan)
        if (json.loads(json.dumps(recipe)) != segment['shot_recipe'] or brief['job_id'] != job.job_id
                or brief['source_binding'] != {'aroll_sha256': arroll['sha256'], 'segment_id': segment['segment_id'],
                                               'start': segment['start'], 'end': segment['end']}
                or brief['template_request'] != json.loads(json.dumps(component['invocation_record']['template_request']))
                or component['template_id'] != DEPENDENCY_ID + '/' + brief['card_id']
                or component['source_sha256'] != entry_sha or sha(SKILL / ENTRY) != entry_sha
                or component['renderer_version'] != renderer_version
                or component['render_window']['start_frame'] != 0
                or component['render_window']['end_frame'] != brief['composition']['frames']
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': False}):
            raise ValueError('TalkCraft differs from the approved Job, recipe or clock')
        source_root(project)
        _inputs(job.job_dir, brief)
        return payload

    def media_loader(job, recipe, component, payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected = native_result_descriptor(job, recipe['segment_id'], component['component_id'], hashlib.sha256(payload).hexdigest())
        result = load_result(job.job_dir, payload, expected_record=expected, expected_renderer_version=renderer_version)
        records = [{'job_path': expected['path'], 'sha256': expected['sha256'], 'byte_count': expected['bytes']}, result['media']]
        return tuple(ReferenceProcessMedia('talkcraft-' + hashlib.sha256(record['job_path'].encode()).hexdigest()[:32],
                                           record['job_path'], record['sha256']) for record in records)

    return ReferenceProcessAdapter(adapter_id='talkcraft-native-skill-v1', dependency_id=DEPENDENCY_ID,
        approved_executor='reference_adapter', dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry_sha, producer_version=VERSION, primary_renderer='Remotion',
        renderer_version=renderer_version, artifact_media_type='video', launcher=launcher,
        launcher_sha256=sha(launcher), self_contained_wrapper=True, brief_loader=guarded_loader,
        media_loader=media_loader, timeout_seconds=120,
        argv_template=('{launcher}', '{entrypoint}', '--skill-root', str(SKILL), '--brief', '{brief_path}',
                       '--media-manifest', '{media_manifest_fd}', '--output', '{output_path}'))


def create_binding(adapter, brief_bytes, reference_sample):
    brief = validate_brief(brief_bytes)
    return {'producer_type': 'dependency', 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'primary_renderer': 'Remotion', 'renderer_version': adapter.renderer_version,
            'template_origin': 'custom_fallback', 'template_id': DEPENDENCY_ID + '/' + brief['card_id'],
            'template_version': VERSION, 'adaptation_level': 'structural',
            'verification_id': hashlib.sha256((adapter.entrypoint_sha256 + hashlib.sha256(brief_bytes).hexdigest()).encode()).hexdigest(),
            'source_entrypoint': ENTRY, 'source_sha256': adapter.entrypoint_sha256, 'sample_sha256': sha(reference_sample),
            'semantic_families': [brief['template_request']['semantic_family']],
            'capacity': {'min_units': 1, 'max_units': brief['template_request']['information_units']},
            'brief_sha256': hashlib.sha256(brief_bytes).hexdigest(),
            'invocation_record': {'argv': [str(adapter.launcher), ENTRY], 'status': 'planned', 'exit_code': None,
                                  'template_request': brief['template_request']}}


def create_artifact_probe(*, ffprobe_executable):
    from edit.hd.tools.material_adapter import create_artifact_probe as factory
    return factory(ffprobe_executable=ffprobe_executable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--brief', type=Path)
    parser.add_argument('--job-dir', type=Path)
    parser.add_argument('--capture-render', action='store_true')
    parser.add_argument('--argv-json')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--call', type=Path)
    parser.add_argument('--qa-note')
    parser.add_argument('--media-manifest', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.probe:
        from prepare_talkcraft_native import check as check_runtime
        runtime = check_runtime(args.project_root)
        print(json.dumps({'schema_version': 1, 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
            'producer_version': VERSION, 'adapter_identity': {'adapter_type': 'ReferenceProcessAdapter',
            'approved_executor': 'reference_adapter', 'primary_renderer': 'Remotion'}}))
    elif args.capture_render:
        print(capture_render(args.job_dir, args.brief, json.loads(args.argv_json)))
    elif args.publish:
        print(publish_completed(args.job_dir, args.brief, args.call, qa_note=args.qa_note))
    else:
        payload = args.brief.read_bytes()
        brief = validate_brief(payload)
        manifest = json.loads(args.media_manifest.read_bytes())
        if manifest['brief_sha256'] != hashlib.sha256(payload).hexdigest():
            raise ValueError('Frozen TalkCraft request differs')
        files = {record['media_ref']: record for record in manifest['media']}
        def read(name):
            record = files['talkcraft-' + hashlib.sha256(name.encode()).hexdigest()[:32]]
            data = Path('/dev/fd/' + str(record['fd'])).read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256'] or len(data) != record['byte_length']:
                raise ValueError('Frozen TalkCraft media differs')
            return data
        result = json.loads(read(brief['result_record_path']))
        if result['request_sha256'] != hashlib.sha256(payload).hexdigest() or result['status'] != 'completed':
            raise ValueError('Frozen TalkCraft result differs')
        video = read(result['media']['job_path'])
        if hashlib.sha256(video).hexdigest() != result['media']['sha256'] or len(video) != result['media']['byte_count']:
            raise ValueError('Frozen TalkCraft output differs from reviewed media')
        args.output.write_bytes(video)
        print(json.dumps({'dependency_id': DEPENDENCY_ID, 'card_id': brief['card_id'],
                          'upstream_commit': UPSTREAM_COMMIT, 'output_sha256': hashlib.sha256(video).hexdigest()}))


if __name__ == '__main__':
    main()

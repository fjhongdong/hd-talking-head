"""Native useAnimations icon playback on the parent transparent canvas."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
if __file__ in ('<stdin>', '/dev/fd/0'):
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument('--skill-root', required=True, type=Path)
    SKILL = bootstrap.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    from package_paths import PACKAGE_ROOT as SKILL
sys.path[:0] = [str(SKILL), str(SKILL / 'scripts')]
from adapter_kit import sha256_file as sha, validate_source_binding

DEPENDENCY_ID='useanimations'
ENTRY='scripts/useanimations_native_adapter.py'
RENDER='scripts/useanimations_render.cjs'
VERSION='3.1.1'
SOURCE_PIN='f7af6f53f6f1a97486ad95756b281a34e9f7c670'
RENDERER_VERSION = '5.12.2'
MAX_LABEL_STATES = 2


def _label_text(value):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 8
            and not any(ord(char) < 32 for char in value))


def validate_planned_content(template_id, pointer, value):
    """Check only the visible inputs known before placement or engineering."""
    if pointer == '/template_id':
        if value != template_id:
            raise ValueError('useAnimations planned icon differs from the selected template')
        return
    index = int(pointer.split('/')[2])
    if index >= MAX_LABEL_STATES or not _label_text(value):
        raise ValueError('useAnimations planned label exceeds the native index or text capacity')


def source_root(project=SKILL):
    from prepare_sources import bundled_source_revision
    from native_result_reuse import source_unchanged
    project = Path(project).resolve(strict=True)
    root = project / 'vendor/react-useanimations'
    if not root.is_dir() or root.resolve() != root:
        raise ValueError('Complete upstream source is missing')
    def verify(_):
        if bundled_source_revision(project, root) != SOURCE_PIN:
            raise ValueError('Upstream source differs from the pinned version')
    return source_unchanged(project, DEPENDENCY_ID, root, verify,
                            records=(project / 'archives/sources/index.json',))

def list_templates(project=SKILL):
    root=source_root(project)/'icons'
    rows=json.loads((root/'catalog.json').read_text())
    if not isinstance(rows,list) or not rows: raise ValueError('Missing upstream icon catalog')
    names=[r['name'] for r in rows]; ids=[r['id'] for r in rows]
    files={p.stem for p in root.glob('*.json')}-{ 'catalog','svg' }
    if len(set(names))!=len(names) or len(set(ids))!=len(ids) or set(names)!=files: raise ValueError('Upstream catalog differs from icon files')
    result=[]
    for row in rows:
        icon=json.loads((root/(row['name']+'.json')).read_text())
        duration=(icon['op']-icon['ip'])/icon['fr']
        if not math.isfinite(duration) or duration<=0: raise ValueError('Invalid native animation duration')
        result.append(dict(template_id='useanimations/'+row['id'],native_id=row['id'],file_name=row['name']+'.json',title=row['title'],tags=row['keywords'],interaction=row['interaction'],min_duration_seconds=duration))
    return result

def validate_brief(payload, *, dependency_id=DEPENDENCY_ID):
    b=json.loads(payload) if isinstance(payload,(str,bytes)) else payload
    keys={'schema_version','source_binding','composition','template_id','template_request','layout','parent_safe_zone','semantic_goal','labels'}
    if not isinstance(b,dict) or set(b)!=keys or b['schema_version']!=1 or dependency_id!=DEPENDENCY_ID: raise ValueError('Invalid useAnimations brief')
    validate_source_binding(b['source_binding'],'Invalid source binding')
    c=b['composition']; zone=b['parent_safe_zone']; layout=b['layout']
    if (not isinstance(c, dict) or set(c) != {'width', 'height', 'fps', 'frames', 'alpha'}
            or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or c['alpha'] is not True or type(c['frames']) is not int or c['frames'] < 1
            or abs((b['source_binding']['end'] - b['source_binding']['start']) * 24 - c['frames']) > 1e-6):
        raise ValueError('Invalid parent clock')
    rows={r['template_id']:r for r in list_templates()}; row=rows.get(b['template_id'])
    if not row or c['frames']/24+1e-8<row['min_duration_seconds']: raise ValueError('Invalid template or insufficient native duration')
    if not isinstance(zone,dict) or set(zone)!={'left','right','top','bottom'} or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in zone.values()): raise ValueError('Invalid safe zone')
    if not isinstance(layout,dict) or set(layout)!={'x','y','size'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in layout.values()): raise ValueError('Invalid placement')
    x,y,size=(layout[k] for k in ('x','y','size'))
    if size<48 or x<zone['left'] or y<zone['top'] or x+size>1080-zone['right'] or y+size>1920-zone['bottom']: raise ValueError('Icon outside safe zone or too small')
    labels = b['labels']
    if not isinstance(labels, list) or len(labels) > MAX_LABEL_STATES:
        raise ValueError('At most two optional label states are allowed')
    for label in labels:
        if (not isinstance(label, dict) or set(label) != {'text', 'start_frame'}
                or not _label_text(label['text'])
                or type(label['start_frame']) is not int
                or not 0 <= label['start_frame'] <= c['frames'] - 24):
            raise ValueError('Invalid label or insufficient reading time')
    if labels and labels[0]['start_frame'] != 0:
        raise ValueError('First label must appear with the icon')
    if len(labels) == 2:
        if labels[0]['text'].split() == labels[1]['text'].split():
            raise ValueError('A state change requires distinct labels')
        if labels[1]['start_frame'] - labels[0]['start_frame'] < 24:
            raise ValueError('Each label needs a full second to read')
        native_frames = math.ceil(row['min_duration_seconds'] * 24)
        if row['interaction'] in {'click-toggle', 'hover'} and c['frames'] - labels[1]['start_frame'] < native_frames:
            raise ValueError('Native transition does not fit after the second state')
    if labels and (x + size + max(48 * len(label['text']) + 48 for label in labels) > 1080-zone['right']
                   or max(size, 60) + y > 1920-zone['bottom']):
        raise ValueError('Caption exceeds parent safe zone')
    if not isinstance(b['semantic_goal'],str) or not b['semantic_goal'].strip(): raise ValueError('Missing icon meaning')
    req=b['template_request']
    if not isinstance(req,dict) or set(req)!={'semantic_family','information_units','numeric_values','numeric_scale'} or not isinstance(req['semantic_family'],str) or not req['semantic_family'] or req['information_units']!=1 or req['numeric_values']!=[] or req['numeric_scale']!='not_applicable': raise ValueError('Invalid semantic request')
    return b

def validate_alignment(brief, *, segment, words, cuts, events):
    from edit.hd.tools.overlay_alignment import validate_native_events
    b = validate_brief(brief)
    if b['labels']:
        actual = [(index, 'reveal', label['text'], label['start_frame']/24)
                  for index, label in enumerate(b['labels'])]
        return validate_native_events(actual, segment=segment, words=words, cuts=cuts, events=events)
    if (not isinstance(events, list) or len(events) != 1 or not isinstance(events[0], dict)
            or events[0].get('slot') != 0 or events[0].get('kind') != 'reveal'):
        raise ValueError('Icon needs a real spoken anchor')
    event = events[0]
    anchor = event.get('anchor', {})
    index = anchor.get('index')
    if type(index) is not int or not 0 <= index < len(words) or words[index]['text'] != anchor.get('text'):
        raise ValueError('Icon anchor is not a real word')
    word = words[index]
    positions = [word['start'] + part['timeline_start'] - part['source_start'] for part in cuts
                 if part['source_start'] <= word['start'] < part['source_end']]
    if (len(positions) != 1 or word['end'] <= word['start']
            or not segment['start'] <= positions[0] < segment['end']
            or event.get('text') != b['semantic_goal'] or event.get('basis') != 'current_clause'
            or not positions[0] - 1 / 24 <= segment['start'] <= positions[0] + 0.8):
        raise ValueError('Icon timing does not match speech')
    return [dict(slot=event.get('slot'), kind=event.get('kind'), text=event['text'],
                 basis=event['basis'], anchor=anchor, anchor_time=positions[0], effective_time=segment['start'])]

def check_runtime(project=SKILL):
    from motion_native_runtime import check
    project = Path(project).resolve(strict=True)
    source_root(project)
    runtime = check(project, dependency_id='barty-motion-graphics')
    lottie = project / 'vendor/talkcraft/demos/_lib/lottie.min.js'
    if not lottie.is_file():
        raise ValueError('Official Lottie player is missing')
    return {'chrome': runtime['browser'], 'node': runtime['tools']['node'],
            'ffmpeg': runtime['tools']['ffmpeg'], 'ffprobe': runtime['tools']['ffprobe'],
            'playwright': str(Path(runtime['node_modules']) / 'playwright'),
            'lottie': str(lottie), 'lottie_sha256': sha(lottie)}

def prepare(project=SKILL):
    from motion_native_runtime import prepare as prepare_motion
    source_root(project)
    prepare_motion(project, dependency_id='barty-motion-graphics')
    return check_runtime(project)

def runtime_fingerprint(runtime):
    data = {key: {'path': runtime[key], 'sha256': sha(Path(runtime[key]))}
            for key in ('node', 'ffmpeg', 'ffprobe', 'chrome', 'lottie')}
    data['playwright_package'] = sha(Path(runtime['playwright']) / 'package.json')
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

def create_adapter(project_root, python_executable, brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter
    project = Path(project_root).resolve(strict=True)
    runtime = check_runtime(project)
    entry, renderer = sha(SKILL / ENTRY), sha(SKILL / RENDER)
    fingerprint = runtime_fingerprint(runtime)
    python = Path(python_executable).resolve(strict=True)
    tool_path = os.pathsep.join(sorted({str(Path(runtime[key]).parent)
                                      for key in ('node', 'ffmpeg', 'ffprobe')}))

    def guard(job, recipe, component):
        from edit.hd.tools import visual_canary
        payload = brief_loader(job, recipe, component)
        brief = validate_brief(payload)
        plan = visual_canary.load_approved_visual_plan(job)
        segment = next(row for row in plan['segments'] if row['segment_id'] == recipe['segment_id'])
        arroll = visual_canary.approved_aroll_record(job, plan)
        source = {'aroll_sha256': arroll['sha256'], 'segment_id': segment['segment_id'],
                  'start': segment['start'], 'end': segment['end']}
        window = component['render_window']
        request = json.loads(json.dumps(component['invocation_record']['template_request']))
        if (brief['source_binding'] != source or json.loads(json.dumps(recipe)) != segment['shot_recipe']
                or recipe['composition']['family'] != 'aroll_with_overlay'
                or component['layer_role'] != 'annotation'
                or component['artifact_contract'] != {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': True}
                or window['safe_zone'] != brief['parent_safe_zone']
                or (window['start_frame'], window['end_frame']) != (0, brief['composition']['frames'])
                or component['template_id'] != brief['template_id'] or component['source_sha256'] != entry
                or request != brief['template_request']):
            raise ValueError('Icon binding differs from approved shot')
        if (sha(SKILL / ENTRY) != entry or sha(SKILL / RENDER) != renderer
                or check_runtime(project) != runtime or runtime_fingerprint(runtime) != fingerprint):
            raise ValueError('Icon renderer or runtime differs from the binding')
        return payload

    return ReferenceProcessAdapter(
        adapter_id='useanimations-native-v1', dependency_id=DEPENDENCY_ID,
        approved_executor='reference_adapter', dependency_root=SKILL, entrypoint=ENTRY,
        entrypoint_sha256=entry, producer_version=VERSION, primary_renderer='Lottie',
        renderer_version=RENDERER_VERSION, artifact_media_type='video', launcher=python,
        launcher_sha256=sha(python), brief_loader=guard, media_loader=None,
        self_contained_wrapper=True, timeout_seconds=300,
        argv_template=('{launcher}', '{entrypoint}', '--skill-root', str(SKILL), '--project-root', str(project),
                       '--brief', '{brief_path}', '--output', '{output_path}', '--render-sha256', renderer,
                       '--runtime-fingerprint', fingerprint, '--tool-path', tool_path))

def create_binding(adapter, brief_bytes):
    b=validate_brief(brief_bytes); digest=hashlib.sha256(brief_bytes).hexdigest(); entry=sha(SKILL/ENTRY)
    if adapter.dependency_id!=DEPENDENCY_ID or adapter.entrypoint_sha256!=entry: raise ValueError('Adapter identity changed')
    return {
        'producer_type': 'dependency', 'dependency_id': DEPENDENCY_ID, 'entrypoint': ENTRY,
        'producer_version': VERSION, 'primary_renderer': 'Lottie', 'renderer_version': RENDERER_VERSION,
        'template_origin': 'custom_fallback', 'template_id': b['template_id'],
        'template_version': VERSION, 'adaptation_level': 'structural',
        'source_entrypoint': ENTRY, 'source_sha256': entry,
        'semantic_families': [b['template_request']['semantic_family']],
        'capacity': {'min_units': 1, 'max_units': 1}, 'brief_sha256': digest,
        'verification_id': hashlib.sha256((entry + digest).encode()).hexdigest(),
        'invocation_record': {'argv': [str(adapter.launcher), ENTRY], 'status': 'planned',
                              'exit_code': None, 'template_request': b['template_request']},
    }

def create_artifact_probe(*,ffprobe_executable):
    from edit.hd.tools.broll_component_executor import ArtifactProbe

    def probe(path, media_type, contract):
        fds = (int(path.name),) if path.parent == Path('/dev/fd') else ()
        result = subprocess.check_output([str(ffprobe_executable), '-v', 'error', '-show_streams',
                                          '-show_format', '-of', 'json', str(path)], pass_fds=fds)
        streams = json.loads(result)['streams']
        if len(streams) != 1 or streams[0]['codec_type'] != 'video':
            raise ValueError('Expected one silent video stream')
        video = streams[0]
        if (media_type != 'video' or contract['alpha'] is not True or video['codec_name'] != 'prores'
                or video['pix_fmt'] != 'yuva444p12le' or (video['width'], video['height']) != (1080, 1920)
                or Fraction(video['avg_frame_rate']) != 24):
            raise ValueError('Invalid transparent ProRes output')
        return {'media_type': 'video', 'container': 'mov', 'codec': 'prores', 'pixel_format': video['pix_fmt'],
                'alpha': True, 'width': 1080, 'height': 1920, 'fps': 24.0,
                'frame_count': int(video['nb_frames']), 'duration': float(video['duration'])}

    return ArtifactProbe(probe_id='useanimations-prores4444-v1', probe_version=VERSION, probe=probe)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--skill-root')
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--brief')
    parser.add_argument('--output')
    parser.add_argument('--render-sha256')
    parser.add_argument('--tool-path')
    parser.add_argument('--runtime-fingerprint')
    args = parser.parse_args()
    if args.tool_path:
        os.environ['PATH'] = args.tool_path + ':/usr/bin:/bin'
    runtime = prepare(args.project_root) if args.prepare else check_runtime(args.project_root)
    if args.prepare or args.probe:
        print(json.dumps(dict(schema_version=1, dependency_id=DEPENDENCY_ID, entrypoint=ENTRY,
              producer_version=VERSION, adapter_identity=dict(adapter_type='ReferenceProcessAdapter',
              approved_executor='reference_adapter', primary_renderer='Lottie'))))
    else:
        raw = Path(args.brief).read_bytes()
        brief = validate_brief(raw)
        row = next(row for row in list_templates(args.project_root) if row['template_id'] == brief['template_id'])
        renderer = SKILL / RENDER
        if (sha(renderer) != args.render_sha256 or sha(Path(runtime['lottie'])) != runtime['lottie_sha256']
                or runtime_fingerprint(runtime) != args.runtime_fingerprint):
            raise ValueError('Renderer or Lottie player changed')
        with tempfile.TemporaryDirectory(prefix='useanimations-native-') as directory:
            tmp = Path(directory)
            brief_file, video_file = tmp / 'brief.json', tmp / 'output.mov'
            brief_file.write_bytes(raw)
            subprocess.run([runtime['node'], str(renderer), '--brief', str(brief_file), '--output', str(video_file),
                '--icon', str(source_root(args.project_root) / 'icons' / row['file_name']),
                '--interaction', row['interaction'], '--lottie', runtime['lottie'], '--playwright', runtime['playwright'],
                '--chrome', runtime['chrome'], '--ffmpeg', runtime['ffmpeg']], check=True, timeout=300)
            create_artifact_probe(ffprobe_executable=runtime['ffprobe']).probe(
                video_file, 'video', {'alpha': True})
            checks = subprocess.check_output([runtime['ffmpeg'], '-v', 'error', '-i', str(video_file),
                '-vf', 'select=eq(n\\,0)+eq(n\\,%d)+eq(n\\,%d),alphaextract,scale=96:171' %
                (brief['composition']['frames']//2, brief['composition']['frames']-1),
                '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], timeout=60)
            if not checks or min(checks) != 0 or max(checks) < 64:
                raise ValueError('Transparent video has no visible icon or no transparent background')
            with open(args.output, 'wb') as output:
                output.write(video_file.read_bytes())

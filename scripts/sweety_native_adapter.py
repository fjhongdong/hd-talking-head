"""Invoke the complete pinned Sweety Skill; consume its real native results."""
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
import wave

if __file__ == '<stdin>':
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument('--skill-root', required=True, type=Path)
    SKILL = bootstrap.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from package_paths import PACKAGE_ROOT
    SKILL = PACKAGE_ROOT
sys.path[:0] = [str(SKILL), str(SKILL / 'scripts')]
from adapter_kit import sha256_file as sha, validate_source_binding
from edit.hd.tools import contract_artifacts as artifacts
from motion_native_skill_adapter import relative, path, descriptor, exact, task_source, approved_task, parent_input_facts, _inputs
from sweety_native_runtime import check as check_runtime, environment, RENDERER_VERSION

DEPENDENCY_ID = 'sweety-handdraw-video'
ENTRY = 'scripts/sweety_native_adapter.py'
VERSION = '1.0.0'
SOURCE_PIN = 'a336506edf2540e4180f8ffa7b19456aa931b897'
SOURCE_RECORD_SHA256 = '4392a3e8c56a615fa12a50158a770dacb86a5ae207f8e99e1c89d81be0d13f76'


def source_root(project=SKILL, *, dependency_id=DEPENDENCY_ID):
    if dependency_id != DEPENDENCY_ID:
        raise ValueError('Unknown Sweety dependency')
    project = Path(project).resolve(strict=True)
    record_path = project / 'references/sweety-handdraw-video-native-source.json'
    if sha(record_path) != SOURCE_RECORD_SHA256:
        raise ValueError('Sweety pinned source record changed')
    record = json.loads(record_path.read_bytes())
    if record['commit'] != SOURCE_PIN:
        raise ValueError('Sweety source commit changed')
    root = path(project, record['source_root'])
    def verify(inventory):
        files = {p.relative_to(root).as_posix() for p in inventory if p.is_file() and not p.is_symlink()}
        links = {p.relative_to(root).as_posix(): str(p.readlink()) for p in inventory if p.is_symlink()}
        if files != set(record['files']) or links != record['symlinks']:
            raise ValueError('The complete unchanged Sweety repository is required')
        for name, digest in record['files'].items():
            if sha(root / relative(name)) != digest:
                raise ValueError('Sweety source changed: ' + name)
    from native_result_reuse import source_unchanged
    return source_unchanged(project, ('sweety', dependency_id), root, verify, records=(record_path,))


def load_template_catalog(project=SKILL, *, dependency_id=DEPENDENCY_ID):
    source_root(project, dependency_id=dependency_id)
    return json.loads((Path(project) / 'references/sweety-handdraw-video-template-catalog.json').read_bytes())['native_paths']


def _template(brief, project=SKILL):
    row = next((r for r in load_template_catalog(project) if r['template_id'] == brief['template_id']), None)
    if row is None:
        raise ValueError('Select an original Sweety style or fixed web-motion recipe')
    if row['native_template_group'] == 'style' and brief['alpha']:
        raise ValueError('Sweety style films have an opaque paper background')
    if row['native_template_group'] == 'web_motion':
        if not brief['alpha'] or brief['composition']['frames'] / 24 > 30:
            raise ValueError('Sweety web motion uses its original transparent 0..30 second renderer')
    return row


def validate_brief(payload, *, dependency_id=DEPENDENCY_ID):
    b = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    required = {'schema_version', 'dependency_id', 'job_id', 'source_binding', 'composition', 'alpha',
                'canvas_transport', 'template_request', 'template_id', 'semantic_goal', 'transcript',
                'word_anchors', 'speech', 'materials', 'authorization', 'project_directory',
                'result_record_path', 'task_source', 'native_options'}
    if (type(b) is not dict or set(b) != required or b['schema_version'] != 2
            or dependency_id != DEPENDENCY_ID or b['dependency_id'] != DEPENDENCY_ID
            or b['native_options'] != [] or b['canvas_transport'] != 'identity'
            or type(b['alpha']) is not bool):
        raise ValueError('Invalid Sweety native task brief')
    validate_source_binding(b['source_binding'], 'Invalid Sweety speech clock')
    c = b['composition']
    if (type(c) is not dict or set(c) != {'width', 'height', 'fps', 'frames'}
            or any(type(c[k]) is not int for k in c) or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or c['frames'] < 1 or abs((b['source_binding']['end']-b['source_binding']['start'])*24-c['frames']) > 1e-6):
        raise ValueError('Sweety requires the exact portrait 24fps parent clock')
    for key in ('job_id', 'template_id', 'semantic_goal', 'transcript'):
        if not isinstance(b[key], str) or not b[key].strip():
            raise ValueError('Sweety requires real content and identity')
    task = b['task_source']
    if (type(task) is not dict or set(task) != {'semantic_row_id','quote','semantic','required_change','component_brief'}
            or any(not isinstance(v, str) or not v.strip() for v in task.values())
            or task['semantic'] != b['semantic_goal']):
        raise ValueError('Sweety task must derive from its approved semantic row')
    r = b['template_request']
    if (type(r) is not dict or set(r) != {'semantic_family','information_units','numeric_values','numeric_scale'}
            or not isinstance(r['semantic_family'], str) or not r['semantic_family']
            or type(r['information_units']) is not int or r['information_units'] < 1
            or type(r['numeric_values']) is not list
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in r['numeric_values'])
            or r['numeric_scale'] not in ({'linear','log'} if r['numeric_values'] else {'not_applicable'})):
        raise ValueError('Invalid Sweety semantic request')
    if not isinstance(b['word_anchors'], list) or not b['word_anchors']:
        raise ValueError('Sweety needs the existing real word clock')
    for word in b['word_anchors']:
        if (type(word) is not dict or set(word) != {'text','start','end'}
                or not isinstance(word['text'], str) or not word['text']
                or any(type(word[k]) not in (int,float) or not math.isfinite(word[k]) for k in ('start','end'))
                or not 0 <= word['start'] < word['end'] <= c['frames']/24):
            raise ValueError('Sweety word clock must be scene-local and real')
    if not isinstance(b['materials'], list) or not isinstance(b['authorization'], dict):
        raise ValueError('Sweety needs actual materials and resource authorization')
    if relative(b['project_directory']).parts[0] != 'native-projects':
        raise ValueError('Sweety project belongs in the current Job native-projects directory')
    if relative(b['result_record_path']).parts[0] != 'native-inputs':
        raise ValueError('Sweety completion belongs in native-inputs')
    _template(b)
    return b


def _execution_job(job_dir):
    from edit.hd.tools.startup import require_job_directory_identity
    return require_job_directory_identity(job_dir, project_root=SKILL)


def validate_selected_inputs(job, director, treatment, *, dependency_id=None):
    from edit.hd.tools.visual_plan import _approved_artifact
    from edit.hd.tools.motion_capabilities import _approved_speech
    from edit.hd.tools.visual_confirmation import local_word_anchors_match
    if dependency_id not in {None, DEPENDENCY_ID}:
        return
    scenes = {(s.get('segment_id'),s.get('component_id')):s for s in treatment.get('scenes',[])}
    for segment in director.get('segments',[]):
        for cid,binding in segment.get('bindings',{}).items():
            if binding.get('dependency_id') != DEPENDENCY_ID:
                continue
            scene = scenes.get((segment['segment_id'],cid),{})
            if not isinstance(scene.get('brief_path'),str):
                raise ValueError('Selected Sweety task requires its actual brief')
            brief_path=path(job.job_dir,scene['brief_path']);payload=brief_path.read_bytes();b=validate_brief(payload)
            expected=task_source(director,treatment,segment['segment_id'],cid)
            beats=[beat for group in ('beats','overlay_beats') for beat in treatment.get('skill_selection',{}).get(group,[])
                   if (beat.get('segment_id'),beat.get('component_id'))==(segment['segment_id'],cid)]
            arroll=sha(_approved_artifact(job,'edit_structure','06-edit-structure/edited-aroll.mp4'))
            words=_approved_speech(Path(job.job_dir))
            anchors=[{'text':w['text'],'start':max(0,w['start']-segment['start']),
                      'end':min(segment['end'],w['end'])-segment['start']}
                     for w in words or [] if w['start']<segment['end'] and w['end']>segment['start']]
            if (any(b['task_source'].get(k)!=expected.get(k) for k in ('semantic_row_id','quote','semantic'))
                    or len(beats)!=1 or b['transcript']!=beats[0].get('transcript')
                    or sha(brief_path)!=binding.get('brief_sha256') or b['job_id']!=job.job_id
                    or b['source_binding']!={'aroll_sha256':arroll,'segment_id':segment['segment_id'],
                                             'start':segment['start'],'end':segment['end']}
                    or not local_word_anchors_match(b['word_anchors'],anchors)
                    or binding.get('template_id')!=DEPENDENCY_ID+'/'+b['template_id']):
                raise ValueError('Sweety selected inputs differ from approved meaning, source or word clock')
            _template(b);_inputs(job.job_dir,b)


def native_task(job, recipe, component, brief_path, *, approved_task_source, defer_runtime=False):
    payload = Path(brief_path).read_bytes(); b = validate_brief(payload); row = _template(b)
    if (b['job_id'] != job.job_id or sha(brief_path) != component['brief_sha256']
            or any(b['task_source'][k] != approved_task_source[k] for k in ('semantic_row_id','quote','semantic'))):
        raise ValueError('Sweety task changed after the parent selection')
    _inputs(job.job_dir, b)
    runtime = ({'status':'pending','check_argv':[sys.executable,'-B',str(SKILL/'scripts/sweety_native_runtime.py'),'--check']}
               if defer_runtime else check_runtime(SKILL))
    directory = path(job.job_dir, b['project_directory'])
    if row['native_template_group'] == 'web_motion':
        instructions = ('Read the entire original Skill and motion-catalog. Author web-motion.json with exactly '
            'template_id, recipe and params in this Job project; use the selected original recipe unchanged. '
            'The native workflow owns params, content, layout and timing. No custom animation, new narration or image generation. '
            'capture_render calls the upstream render function at the real 24fps clock and encodes its alpha PNG sequence. '
            'Run publish_completed after actual completion; the parent consumes the result, not a placeholder.')
    else:
        instructions = ('Read and execute the complete original SKILL.md and all selected style instructions. '
            'Use prepare_narration to import the existing speech and word clock via original align.py --words; never synthesize TTS. '
            'Author only this Job native project, preserve every vendor file, and run original build. '
            'Use the complete selected catalog recipe, original art direction, drawing plans, storyboard, native QA and truthful review. '
            'Reuse the real supplied images or wait for authorized image generation; do not fabricate generation evidence. '
            'For reveal retain the native informed choice/reveal_accepted evidence; parent automatic selection is not acceptance. '
            'This product is silent visual material: existing speech supplies the clock only; do not mix audio, render a full film or run finalize. '
            'Native frames burn subtitles: retain them as this scene\'s only ordinary subtitles; the parent suppresses its duplicate track in this window. '
            'capture_render runs original assets-only verification, locked-master/timeline checks and render_chunk; '
            'publish_completed requires those actual visual checks and a video with zero audio streams. No full-film QA pass is implied.')
    return {'action':'execute_native_skill','dependency_id':DEPENDENCY_ID,'native_template':row,
            'native_instructions':row['native_instructions'],'native_options':[], 'task_source':b['task_source'],
            'template_id':DEPENDENCY_ID+'/'+b['template_id'],'skill_path':str(SKILL/row['skill_path']),
            'job_dir':str(job.job_dir),'brief_path':str(brief_path),'brief_sha256':sha(brief_path),
            'project_directory':str(directory),'runtime':runtime,'segment_id':recipe['segment_id'],
            'component_id':component['component_id'],'requirements':{**b['composition'],'alpha':b['alpha'],'silent':True,
            'canvas_transport':'identity','native_captions':row['native_template_group']=='style',
            'semantic_goal':b['semantic_goal'],'transcript':b['transcript'],'word_anchors':b['word_anchors'],
            'authorization':b['authorization']},'speech':str(path(job.job_dir,b['speech']['job_path'])),
            'source_binding':b['source_binding'],'materials':[str(path(job.job_dir,m['job_path'])) for m in b['materials']],
            'result_record_path':b['result_record_path'],'next':instructions}


def tail_fade_interval(duration, last_word_end, *, quiet_tail=.12):
    if (not all(type(v) in (int,float) and math.isfinite(v) for v in (duration,last_word_end,quiet_tail))
            or not 0 <= last_word_end < duration or quiet_tail < .12
            or duration-last_word_end < quiet_tail+.05):
        raise ValueError('The real source window has insufficient post-word pause for native tail protection')
    return {'start':last_word_end,'end':duration-quiet_tail,'quiet_tail_seconds':quiet_tail}


def _pcm(pathname):
    with wave.open(str(pathname),'rb') as stream:
        if stream.getnchannels()!=1 or stream.getsampwidth()!=2 or stream.getframerate() not in {16000,48000}:
            raise ValueError('Sweety requires the real mono 16-bit PCM parent clip at 16kHz or native 48kHz')
        if stream.getframerate()==48000:
            return stream.readframes(stream.getnframes())
    ffmpeg=check_runtime(mode='reuse')['tools']['ffmpeg']
    return subprocess.check_output([ffmpeg,'-v','error','-nostdin','-i',str(pathname),
                                    '-af','aresample=48000','-ac','1','-ar','48000','-f','s16le','-c:a','pcm_s16le','-'])


def verify_narration_import(job_dir,b,directory):
    directory=Path(directory).resolve(strict=True)
    manifest=json.loads((directory/'job.json').read_bytes());settings=manifest.get('narration',{})
    processed=(directory/relative(settings.get('source',''))).resolve(strict=True);processed.relative_to(directory)
    record_path=directory/('inputs/narration/parent-import-tail.json' if processed.name=='master-tail.wav' else 'inputs/narration/parent-import.json')
    record=json.loads(record_path.read_bytes())
    if (record.get('raw_source')!=b['speech'] or record.get('word_anchors_sha256')!=artifacts.sha256_json(b['word_anchors'])
            or record.get('processed_sha256')!=sha(processed) or record.get('raw_sha256')!=b['speech']['sha256']):
        raise ValueError('Sweety narration import does not match its approved real inputs')
    original=exact(job_dir,record['raw_copy']);raw=_pcm(original);changed=_pcm(processed)
    with wave.open(str(processed),'rb') as stream:
        if stream.getframerate()!=48000:
            raise ValueError('Sweety native master must use 48kHz PCM')
    if sha(original)!=b['speech']['sha256']:
        raise ValueError('Sweety raw narration copy differs from the approved parent speech')
    duration=len(raw)/96000
    if len(raw)!=len(changed) or abs(duration-b['composition']['frames']/24)>1/48000+1e-9:
        raise ValueError('Sweety narration preparation changed duration')
    fade=record.get('tail_fade')
    if fade is None:
        if raw!=changed:
            raise ValueError('Sweety unprocessed narration must preserve every sample')
    else:
        expected=tail_fade_interval(duration,max(w['end'] for w in b['word_anchors']))
        if fade!=expected:
            raise ValueError('Sweety fade may only use the real pause after the final word')
        prefix=math.ceil(expected['start']*48000)*2
        if raw[:prefix]!=changed[:prefix] or any(changed[math.ceil(expected['end']*48000)*2:]):
            raise ValueError('Sweety fade changed spoken samples or failed to preserve the required quiet tail')
    # The parent descriptor stays bound to raw 16kHz speech. Compare both sides
    # on one native 48kHz clock, with no gain, denoising, padding or retiming.
    ffmpeg=check_runtime(mode='reuse')['tools']['ffmpeg'];filter_text=_narration_filter(fade)
    if (record.get('filter')!=filter_text or record.get('argv')!=_narration_command(ffmpeg,original,processed,fade)):
        raise ValueError('Sweety import command differs from its bounded ordinary audio preparation')
    actual=subprocess.check_output([ffmpeg,'-v','error','-nostdin','-i',str(original),'-af',filter_text,
                                    '-ac','1','-ar','48000','-f','s16le','-c:a','pcm_s16le','-'])
    if actual!=changed:
        raise ValueError('Sweety prepared narration differs from its recorded resampling and bounded tail fade')
    return processed,record


def _fade_filter(interval):
    return f"afade=t=out:st={interval['start']:.12f}:d={interval['end']-interval['start']:.12f}"


def _narration_filter(fade):
    return 'aresample=48000'+(','+_fade_filter(fade) if fade is not None else '')


def _narration_command(ffmpeg,original,target,fade):
    return [ffmpeg,'-v','error','-nostdin','-n','-i',str(original),'-af',_narration_filter(fade),
            '-ac','1','-ar','48000','-c:a','pcm_s16le',str(target)]


def prepare_narration(job_dir, brief_path, *, tail_fade=False):
    """Import real inputs through the original aligner; never generate or invent speech."""
    b = validate_brief(Path(brief_path).read_bytes()); _inputs(job_dir,b)
    if _template(b)['native_template_group'] != 'style':
        raise ValueError('Web components do not require a new narration master')
    directory = path(job_dir,b['project_directory']); manifest_path = directory/'job.json'
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('runtime_fixture') or ''.join(x['text'] for p in manifest['pages'] for x in p['beats']) != b['transcript']:
        raise ValueError('Sweety native beats must retain the real approved transcript')
    target=directory/('inputs/narration/master-tail.wav' if tail_fade else 'inputs/narration/master.wav')
    original=directory/('inputs/narration/parent-source-tail.wav' if tail_fade else 'inputs/narration/parent-source.wav')
    words=directory/'inputs/narration/parent-words.json'
    if target.exists() or original.exists():
        raise ValueError('Preserve existing imported speech; use a new native revision')
    target.parent.mkdir(parents=True,exist_ok=True)
    source=exact(job_dir,b['speech']);shutil.copyfile(source,original)
    raw=_pcm(original);duration=len(raw)/96000
    interval=tail_fade_interval(duration,max(w['end'] for w in b['word_anchors'])) if tail_fade else None
    ffmpeg=check_runtime(mode='reuse')['tools']['ffmpeg'];command=_narration_command(ffmpeg,original,target,interval)
    subprocess.run(command,check=True,capture_output=True,text=True)
    record={'raw_source':b['speech'],'raw_sha256':sha(source),'raw_copy':descriptor(job_dir,original),
            'word_anchors_sha256':artifacts.sha256_json(b['word_anchors']),'tail_fade':interval,
            'filter':_narration_filter(interval),'argv':command}
    record['processed_sha256']=sha(target)
    record_name='parent-import-tail.json' if tail_fade else 'parent-import.json'
    artifacts.write_json_artifact(target.parent/record_name,record)
    if words.exists():
        if json.loads(words.read_bytes())!={'words':b['word_anchors']}:
            raise ValueError('Preserve the existing different word clock')
    else:
        artifacts.write_json_artifact(words,{'words':b['word_anchors']})
    alignment_name='alignment-tail.json' if tail_fade else 'alignment.json'
    manifest['narration']={'source':target.relative_to(directory).as_posix(),'alignment':'inputs/narration/'+alignment_name}
    manifest['canvas']={'aspect_ratio':'9:16','width':1080,'height':1920,'fps':24}
    artifacts.write_json_artifact(manifest_path,manifest)
    verify_narration_import(job_dir,b,directory)
    script=source_root()/'skills/sweety-handdraw-video/scripts/align.py'
    subprocess.run([sys.executable,'-B',str(script),str(directory),'--words',str(words)],
                   env=environment(),check=True,capture_output=True,text=True,timeout=120)
    return directory/'inputs/narration'/alignment_name


def project_files(root,directory):
    # Keep native build/output caches separate from authored content and inputs.
    return [descriptor(root,p) for p in sorted(directory.rglob('*')) if p.is_file()
            and p.relative_to(directory).parts[0] not in {'out','work','outputs'}
            and p.relative_to(directory).as_posix() != 'review.json']


def _run(argv,cwd,env):
    result=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,text=True,timeout=1200)
    if result.returncode:
        raise ValueError('Original Sweety execution failed: '+result.stderr[-2000:])
    return {'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}


def _silent_probe(media, composition, alpha):
    # The shared probe requires exactly one H.264/ProRes video stream, so any
    # audio stream is rejected as part of the same format/frame-count check.
    from motion_native_skill_adapter import probe
    if probe(media,alpha=alpha)!=composition:
        raise ValueError('Sweety actual media differs from the approved format')


def _visual_inputs(root,directory):
    """Bind files read by the original Renderer, not unrelated build caches."""
    root=Path(root).resolve(strict=True);directory=Path(directory).resolve(strict=True)
    directory.relative_to(root)
    # These are native write locations, so the read-only vendor exception below
    # must never apply to them, including pre-existing review/output children.
    for target in (directory/'out',directory/'work/watermark-plan.json',directory/'work/review'):
        current=directory
        for part in target.relative_to(directory).parts:
            current=current/part
            if current.is_symlink():
                raise ValueError('Sweety native output must not use a symlink: '+str(current))
        if (not target.resolve().is_relative_to(directory)
                or (target.is_dir() and any(p.is_symlink() for p in target.rglob('*')))):
            raise ValueError('Sweety native output must stay in the current project without symlinks: '+str(target))
    vendor=source_root().resolve(strict=True);files=set()
    def add(value):
        target=Path(value)
        target=(target if target.is_absolute() else directory/target).resolve(strict=True)
        if target.is_relative_to(vendor):
            return  # The complete official source, including assets, is already pinned.
        if not target.is_relative_to(root):
            raise ValueError('Sweety visual dependency escapes the current Job: '+str(target))
        if not target.is_file():
            raise ValueError('Sweety visual dependency is not a file: '+str(target))
        files.add(target)
    add(directory/'work/timeline.json');add(directory/'work/narration.wav');add(directory/'outputs/cover.png')
    timeline=json.loads((directory/'work/timeline.json').read_bytes())
    if timeline.get('narration_master'):
        for key in ('source','alignment'):
            add(timeline['narration_master'][key])
    assets=directory/'work/assets'
    for name,metadata in timeline['assets'].items():
        relative(name)  # Asset names must not escape their native cache directory.
        add(assets/f'{name}.png');add(assets/f'{name}.npz')
        if (assets/f'{name}-line.png').exists():
            for suffix in ('line','paint','shade'):
                add(assets/f'{name}-{suffix}.png')
            if (assets/f'{name}-sketch.png').exists():
                add(assets/f'{name}-sketch.png')
        if metadata.get('type')=='counter':
            add(metadata['counter']['font']['path'])
    add(timeline['hand']['source'])
    if timeline.get('watermark'):
        add(timeline['watermark']['source'])
        if (directory/'work/watermark-plan.json').exists():
            add(directory/'work/watermark-plan.json')
    for page in timeline['pages']:
        if page.get('background'):
            add(page['background'])
        for overlay in page.get('overlays',[]):
            if type(overlay['count']) is not int or overlay['count']<1:
                raise ValueError('Sweety overlay requires its actual native frame count')
            frames=Path(overlay['frames'])
            for index in range(overlay['count']):
                add(frames/f'{index:05d}.png')
    return [descriptor(root,p) for p in sorted(files)]


def _validate_web_expression(config, basis):
    from edit.hd.tools.motion_match_cache import validate_fixed_content
    from sweety_native_runtime import kinetic_title_content

    if not isinstance(basis, dict) or not basis.get('content'):
        raise ValueError('Sweety kinetic title needs its confirmed visible content')
    validate_fixed_content(kinetic_title_content(config), basis)


def _web_config(root, brief):
    relative_path = relative(brief['project_directory']) / 'web-motion.json'
    return artifacts.read_json_artifact(path(root, relative_path.as_posix()))


def capture_render(job_dir,brief_path,argv=None,*,native_preparations=None):
    from edit.hd.tools.visual_confirmation import require_native_dispatch

    job=_execution_job(job_dir);payload=Path(brief_path).read_bytes();b=validate_brief(payload)
    if b['job_id']!=job.job_id or native_preparations is not None:
        raise ValueError('Sweety requires this Job; no substitute preparation workflow')
    task = require_native_dispatch(job, DEPENDENCY_ID, Path(brief_path), payload=payload)
    return _capture_native(job_dir,brief_path,argv,payload=payload,task=task)


def _capture_native(job_dir,brief_path,argv=None,*,payload=None,task=None):
    """The same mechanical native invocation used by production and isolated source qualification.

    A capability sample is not a production Job or a user semantic approval.
    The public production entry above still requires its actual Job identity.
    """
    root=Path(job_dir).resolve(strict=True)
    payload=Path(brief_path).read_bytes() if payload is None else payload
    b=validate_brief(payload)
    _inputs(root,b);row=_template(b);directory=path(root,b['project_directory'])
    if row['native_template_group']=='web_motion':
        config=_web_config(root,b)
        if (not isinstance(config, dict) or config.get('template_id')!=b['template_id']
                or config.get('recipe')!=row['native_option_id']):
            raise ValueError('Sweety native recipe changed from the selected template')
        if task is not None and b['template_id']=='web-kinetic-title':
            _validate_web_expression(config,task.get('expression_basis'))
    runtime=check_runtime()
    directory.mkdir(parents=True,exist_ok=True)
    out=directory/'out';out.mkdir(exist_ok=True)
    target=out/('visual.mov' if b['alpha'] else 'visual.mp4')
    result_relative=relative(b['result_record_path']);call_path=path(root,result_relative.with_name(result_relative.stem+'.render-call.json').as_posix())
    if target.exists() or call_path.exists():
        raise ValueError('Preserve completed or failed native execution; use a new revision')
    before=project_files(root,directory)
    record={'schema_version':1,'dependency_id':DEPENDENCY_ID,'upstream_commit':SOURCE_PIN,
            'request_sha256':hashlib.sha256(payload).hexdigest(),'renderer_version':RENDERER_VERSION,
            'runtime_helper_sha256':sha(SKILL/'scripts/sweety_native_runtime.py'),
            'project_files':before,'status':'running','exit_code':None,'steps':[]}
    record['runtime_identity']={k:runtime[k] for k in ('python','browser','browser_version','packages','renderer_version','tools')}
    artifacts.write_json_artifact(call_path,record)
    try:
        if row['native_template_group']=='web_motion':
            command=[runtime['python'],'-B',str(SKILL/'scripts/sweety_native_runtime.py'),'--render-web',str(directory),
                     '--composition-json',json.dumps(b['composition'],separators=(',',':'))]
            if argv is not None and argv!=command:
                raise ValueError('Sweety web capture calls only its original recipe renderer')
            record['steps'].append(_run(command,directory,environment()))
            native=json.loads((out/'web-motion-result.json').read_bytes())
            if native.get('clipped'):
                raise ValueError('Original Sweety component reports clipped settled content')
            frames=Path(native['directory']);frames.relative_to(out.resolve())
            if native['fps']!=24 or native['frames']!=b['composition']['frames']+1 or native['size']!=[1080,1920]:
                raise ValueError('Original Sweety PNG clock or size changed')
            command=[runtime['tools']['ffmpeg'],'-v','error','-nostdin','-n','-framerate','24','-i',str(frames/'%05d.png'),
                     '-frames:v',str(b['composition']['frames']),'-an','-c:v','prores_ks','-profile:v','4',
                     '-pix_fmt','yuva444p10le','-vendor','apl0',str(target)]
            record['steps'].append(_run(command,directory,environment()))
            record['native_frames']=[descriptor(root,frames/f'{n:05d}.png') for n in range(native['frames'])]
            record['native_script_sha256']=sha(source_root()/'skills/sweety-handdraw-video/scripts/web_motion.py')
        else:
            native=source_root()/'skills/sweety-handdraw-video/scripts/video_renderer.py'
            command=[runtime['python'],'-B',str(SKILL/'scripts/sweety_native_runtime.py'),'--render-style',str(directory),
                     '--job-root',str(root),
                     '--composition-json',json.dumps(b['composition'],separators=(',',':'))]
            if argv is not None and argv!=command:
                raise ValueError('Sweety style capture requires the original video-only visual renderer')
            config=json.loads((directory/'job.json').read_bytes())
            if config.get('runtime_fixture'):
                raise ValueError('A Sweety runtime fixture can never become B-roll')
            style=json.loads((directory/'style/resolved.json').read_bytes())
            if style.get('catalog_id')!=row['native_option_id']:
                raise ValueError('Sweety film must retain the selected native catalog style')
            verify_narration_import(root,b,directory)
            record['steps'].append(_run(command,directory,environment()))
            record['native_script_sha256']=sha(native)
            record['native_visual_checks']=descriptor(root,out/'style-visual-checks.json')
            checks=json.loads((out/'style-visual-checks.json').read_bytes())
            record['native_visual_inputs']=checks['visual_inputs']
            if _visual_inputs(root,directory)!=record['native_visual_inputs']:
                raise ValueError('Sweety visual dependencies changed after native rendering')
            record['subtitle_owner']='native_burned'
            record['native_captions']=True
        _silent_probe(target,b['composition'],b['alpha'])
        if project_files(root,directory)!=before:
            raise ValueError('Sweety actual output clock or authored inputs changed')
        source_root()
        record.update(status='completed',exit_code=0,media=descriptor(root,target))
    except BaseException as error:
        record.update(status='failed',error=str(error));raise
    finally:
        artifacts.write_json_artifact(call_path,record)
    return call_path


def _verify_call(root,b,payload,call):
    row=_template(b)
    if (call.get('status')!='completed' or call.get('exit_code')!=0 or call.get('dependency_id')!=DEPENDENCY_ID
            or call.get('request_sha256')!=hashlib.sha256(payload).hexdigest() or call.get('upstream_commit')!=SOURCE_PIN
            or call.get('renderer_version')!=RENDERER_VERSION
            or len(call.get('steps',[]))!=(2 if row['native_template_group']=='web_motion' else 1)
            or any(s.get('exit_code')!=0 for s in call['steps'])):
        raise ValueError('Sweety result does not match completed native execution')
    directory=path(root,b['project_directory']);script=source_root()/'skills/sweety-handdraw-video/scripts'/('web_motion.py' if row['native_template_group']=='web_motion' else 'video_renderer.py')
    if (call['native_script_sha256']!=sha(script) or project_files(root,directory)!=call['project_files']
            or call.get('runtime_helper_sha256')!=sha(SKILL/'scripts/sweety_native_runtime.py')):
        raise ValueError('Sweety native source or authored project changed')
    runtime=call.get('runtime_identity',{})
    python=runtime.get('python');tools=runtime.get('tools',{})
    if (not isinstance(python,str) or not Path(python).is_absolute()
            or set(tools)!={'ffmpeg','ffprobe'} or runtime.get('renderer_version')!=RENDERER_VERSION):
        raise ValueError('Sweety native execution runtime is missing')
    if row['native_template_group']=='web_motion':
        expected=[python,'-B',str(SKILL/'scripts/sweety_native_runtime.py'),'--render-web',str(directory),
                  '--composition-json',json.dumps(b['composition'],separators=(',',':'))]
        if call['steps'][0]['argv']!=expected or len(call.get('native_frames',[]))!=b['composition']['frames']+1:
            raise ValueError('Sweety call did not use the original fixed recipe renderer')
        frame_directory=path(root,call['native_frames'][0]['job_path']).parent
        expected=[tools['ffmpeg'],'-v','error','-nostdin','-n','-framerate','24','-i',str(frame_directory/'%05d.png'),
                  '-frames:v',str(b['composition']['frames']),'-an','-c:v','prores_ks','-profile:v','4',
                  '-pix_fmt','yuva444p10le','-vendor','apl0',str(path(root,b['project_directory'])/'out/visual.mov')]
        if call['steps'][1]['argv']!=expected:
            raise ValueError('Sweety alpha encoding changed the original frame clock')
    elif call['steps'][0]['argv']!=[python,'-B',str(SKILL/'scripts/sweety_native_runtime.py'),'--render-style',str(directory),
                                  '--job-root',str(Path(root).resolve(strict=True)),
                                  '--composition-json',json.dumps(b['composition'],separators=(',',':'))]:
        raise ValueError('Sweety call did not execute the original video-only visual renderer')
    for item in call.get('native_frames',[]):
        exact(root,item)
    media=exact(root,call['media'])
    _silent_probe(media,b['composition'],b['alpha'])
    if row['native_template_group']=='style':
        checks=json.loads(exact(root,call['native_visual_checks']).read_bytes())
        if (checks.get('scope')!='silent_visual_material' or checks.get('native_full_film_verified') is not False
                or checks.get('composition')!=b['composition'] or checks.get('native_captions') is not True
                or checks.get('first_frame')!=0 or checks.get('media')!=str(media)
                or set(checks.get('checks',{}))!={'verify_job_assets_only','verify_compiled_master','validate_timeline'}
                or checks['checks']['validate_timeline'] is not True
                or not checks['checks']['verify_compiled_master']
                or checks.get('visual_inputs')!=call.get('native_visual_inputs')
                or _visual_inputs(root,directory)!=call.get('native_visual_inputs')):
            raise ValueError('Sweety style result needs its actual original visual checks and unchanged built assets')
        manifest=json.loads((directory/'job.json').read_bytes())
        timeline=json.loads((directory/'work/timeline.json').read_bytes())
        if checks.get('voice_start_seconds')!=timeline.get('voice_start_seconds',timeline['cover_seconds']):
            raise ValueError('Sweety native visual start differs from its built speech clock')
        narration=manifest.get('narration',{})
        master,import_record=verify_narration_import(root,b,directory)
        alignment=(directory/relative(narration.get('alignment',''))).resolve(strict=True)
        master.relative_to(directory);alignment.relative_to(directory)
        aligned=json.loads(alignment.read_bytes())
        if (aligned.get('source_sha256')!=sha(master)
                or ''.join(beat['text'] for p in manifest['pages'] for beat in p['beats'])!=b['transcript']
                or call.get('native_captions') is not True):
            raise ValueError('Native Sweety captions must use this exact speech, transcript and original aligned master')


def publish_completed(job_dir,brief_path,call_path,*,native_usage=None):
    from edit.hd.tools.visual_confirmation import require_native_dispatch

    job=_execution_job(job_dir);payload=Path(brief_path).read_bytes();b=validate_brief(payload)
    if b['job_id']!=job.job_id or native_usage is not None:
        raise ValueError('Sweety completion belongs to this exact native task')
    task = require_native_dispatch(job, DEPENDENCY_ID, Path(brief_path), payload=payload)
    if b['template_id']=='web-kinetic-title':
        _validate_web_expression(_web_config(job_dir,b),task.get('expression_basis'))
    return _publish_native(job_dir,brief_path,call_path,payload=payload)


def _publish_native(job_dir,brief_path,call_path,*,payload=None):
    """Publish actual native completion; source qualification does not assert Job approval."""
    payload=Path(brief_path).read_bytes() if payload is None else payload
    b=validate_brief(payload)
    _inputs(job_dir,b);call=json.loads(Path(call_path).read_bytes());_verify_call(job_dir,b,payload,call)
    target=path(job_dir,b['result_record_path'])
    if target.exists():
        raise ValueError('Preserve the completed Sweety result')
    artifacts.write_json_artifact(target,{'schema_version':3,'status':'completed','dependency_id':DEPENDENCY_ID,
        'job_id':b['job_id'],'template_id':b['template_id'],'request_sha256':hashlib.sha256(payload).hexdigest(),
        'media':call['media'],'media_probe':b['composition'],'alpha':b['alpha'],
        'renderer_version':RENDERER_VERSION,'render_call':descriptor(job_dir,call_path),
        'product_scope':'silent_visual_material',
        'native_captions':_template(b)['native_template_group']=='style',
        'subtitle_owner':'sweety_native' if _template(b)['native_template_group']=='style' else 'parent'})
    return target


def inspect_result(job_dir,payload,*,record_bytes=None):
    b=validate_brief(payload);_inputs(job_dir,b)
    data=record_bytes if record_bytes is not None else path(job_dir,b['result_record_path']).read_bytes()
    result=json.loads(data)
    expected={'schema_version':3,'status':'completed','dependency_id':DEPENDENCY_ID,'job_id':b['job_id'],
              'template_id':b['template_id'],'request_sha256':hashlib.sha256(payload).hexdigest(),
              'media_probe':b['composition'],'alpha':b['alpha'],'renderer_version':RENDERER_VERSION}
    expected['product_scope']='silent_visual_material'
    expected['native_captions']=_template(b)['native_template_group']=='style'
    expected['subtitle_owner']='sweety_native' if expected['native_captions'] else 'parent'
    if any(result.get(k)!=v for k,v in expected.items()):
        raise ValueError('Sweety completion differs from its actual request')
    call=json.loads(exact(job_dir,result['render_call']).read_bytes());_verify_call(job_dir,b,payload,call)
    if result['media']!=call['media']:
        raise ValueError('Sweety result media changed')
    return result


def load_result(job_dir,payload,*,expected_record,expected_renderer_version=RENDERER_VERSION):
    b=validate_brief(payload)
    if expected_record.get('path')!=b['result_record_path'] or expected_renderer_version!=RENDERER_VERSION:
        raise ValueError('Sweety result binding changed')
    data=path(job_dir,expected_record['path']).read_bytes()
    if len(data)!=expected_record['bytes'] or hashlib.sha256(data).hexdigest()!=expected_record['sha256']:
        raise ValueError('Sweety result differs from the frozen result')
    return inspect_result(job_dir,payload,record_bytes=data)


def create_adapter(project_root,python_executable,brief_loader,*,renderer_version=None,dependency_id=DEPENDENCY_ID):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter,ReferenceProcessMedia
    source_root(project_root,dependency_id=dependency_id);check_runtime(project_root,mode='reuse')
    if renderer_version not in (None,RENDERER_VERSION):
        raise ValueError('Unknown Sweety renderer')
    entry_sha=sha(SKILL/ENTRY);launcher=Path(python_executable).resolve(strict=True)
    def guard(job,recipe,component):
        from edit.hd.tools import visual_canary
        payload=brief_loader(job,recipe,component);b=validate_brief(payload)
        plan=visual_canary.load_approved_visual_plan(job)
        segment=next(s for s in plan['segments'] if s['segment_id']==recipe['segment_id'])
        ar=visual_canary.approved_aroll_record(job,plan)
        if (json.loads(json.dumps(recipe))!=segment['shot_recipe'] or b['job_id']!=job.job_id
                or b['source_binding']!={'aroll_sha256':ar['sha256'],'segment_id':segment['segment_id'],'start':segment['start'],'end':segment['end']}
                or b['template_request']!=json.loads(json.dumps(component['invocation_record']['template_request']))
                or component['template_id']!=DEPENDENCY_ID+'/'+b['template_id'] or component['source_sha256']!=entry_sha
                or sha(SKILL/ENTRY)!=entry_sha or component['renderer_version']!=RENDERER_VERSION
                or component['artifact_contract']!={'width':1080,'height':1920,'fps':24,'alpha':b['alpha']}
                or component['render_window'].get('start_frame')!=0 or component['render_window'].get('end_frame')!=b['composition']['frames']):
            raise ValueError('Sweety component differs from its approved Job, input or clock')
        _inputs(job.job_dir,b);return payload
    def media_loader(job,recipe,component,payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected=native_result_descriptor(job,recipe['segment_id'],component['component_id'],hashlib.sha256(payload).hexdigest())
        result=load_result(job.job_dir,payload,expected_record=expected)
        return tuple(ReferenceProcessMedia('sweety-'+hashlib.sha256(r['job_path'].encode()).hexdigest()[:32],r['job_path'],r['sha256'])
                     for r in [{'job_path':expected['path'],'sha256':expected['sha256']},result['media']])
    return ReferenceProcessAdapter(adapter_id='sweety-native-skill-v1',dependency_id=DEPENDENCY_ID,
        approved_executor='reference_adapter',dependency_root=SKILL,entrypoint=ENTRY,entrypoint_sha256=entry_sha,
        producer_version=VERSION,primary_renderer='HTMLCanvas',renderer_version=RENDERER_VERSION,
        artifact_media_type='video',launcher=launcher,launcher_sha256=sha(launcher),self_contained_wrapper=True,
        brief_loader=guard,media_loader=media_loader,timeout_seconds=120,
        argv_template=('{launcher}','{entrypoint}','--skill-root',str(SKILL),'--brief','{brief_path}',
                       '--media-manifest','{media_manifest_fd}','--output','{output_path}'))


def create_binding(adapter,brief_bytes):
    b=validate_brief(brief_bytes);digest=hashlib.sha256(brief_bytes).hexdigest()
    return {'producer_type':'dependency','dependency_id':DEPENDENCY_ID,'entrypoint':ENTRY,'producer_version':VERSION,
        'primary_renderer':'HTMLCanvas','renderer_version':RENDERER_VERSION,'template_origin':'custom_fallback',
        'template_id':DEPENDENCY_ID+'/'+b['template_id'],'template_version':VERSION,'adaptation_level':'structural',
        'source_entrypoint':ENTRY,'source_sha256':adapter.entrypoint_sha256,'brief_sha256':digest,
        'verification_id':hashlib.sha256((adapter.entrypoint_sha256+digest).encode()).hexdigest(),
        'semantic_families':[b['template_request']['semantic_family']],
        'capacity':{'min_units':1,'max_units':b['template_request']['information_units']},
        'invocation_record':{'argv':[str(adapter.launcher),ENTRY],'status':'planned','exit_code':None,'template_request':b['template_request']}}


def create_artifact_probe(*,ffprobe_executable):
    from edit.hd.tools.material_adapter import create_artifact_probe as factory
    return factory(ffprobe_executable=ffprobe_executable)


def consume_result(payload,manifest,output):
    """Consume only the executor's hash-checked media descriptors, without rendering again."""
    b=validate_brief(payload)
    if manifest['brief_sha256']!=hashlib.sha256(payload).hexdigest():
        raise ValueError('Sweety frozen request changed')
    rows={r['media_ref']:r for r in manifest['media']}
    def read(name):
        r=rows['sweety-'+hashlib.sha256(name.encode()).hexdigest()[:32]]
        data=Path('/dev/fd/'+str(r['fd'])).read_bytes()
        if len(data)!=r['byte_length'] or hashlib.sha256(data).hexdigest()!=r['sha256']:
            raise ValueError('Sweety frozen input changed')
        return data
    result=json.loads(read(b['result_record_path']))
    if (result.get('request_sha256')!=hashlib.sha256(payload).hexdigest() or result.get('status')!='completed'
            or result.get('dependency_id')!=DEPENDENCY_ID or result.get('template_id')!=b['template_id']):
        raise ValueError('Sweety frozen completion changed')
    video=read(result['media']['job_path'])
    if hashlib.sha256(video).hexdigest()!=result['media']['sha256'] or len(video)!=result['media']['byte_count']:
        raise ValueError('Sweety frozen video changed')
    target = Path(output)
    # The parent supplies an already opened output descriptor. Regular sample
    # paths still use exclusive creation so a result is never overwritten.
    mode = 'wb' if re.fullmatch(r'/dev/fd/[0-9]+', str(target)) else 'xb'
    with target.open(mode) as stream:
        stream.write(video)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root',type=Path);parser.add_argument('--project-root',type=Path,default=SKILL)
    parser.add_argument('--dependency-id',choices=[DEPENDENCY_ID],default=DEPENDENCY_ID)
    parser.add_argument('--brief',type=Path)
    parser.add_argument('--job-dir',type=Path,default=os.environ.get('BROLL_JOB_DIR'))
    parser.add_argument('--capture-render',action='store_true');parser.add_argument('--argv-json')
    parser.add_argument('--prepare-narration',action='store_true');parser.add_argument('--tail-fade',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--call',type=Path);parser.add_argument('--media-manifest',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--probe',action='store_true');args=parser.parse_args()
    if args.probe:
        source_root(args.project_root,dependency_id=args.dependency_id);check_runtime(args.project_root)
        print(json.dumps({'schema_version':1,'dependency_id':DEPENDENCY_ID,'entrypoint':ENTRY,
            'producer_version':VERSION,'adapter_identity':{'adapter_type':'ReferenceProcessAdapter',
            'approved_executor':'reference_adapter','primary_renderer':'HTMLCanvas'}}))
    elif args.prepare_narration:
        print(prepare_narration(args.job_dir,args.brief,tail_fade=args.tail_fade))
    elif args.capture_render:
        print(capture_render(args.job_dir,args.brief,json.loads(args.argv_json) if args.argv_json else None))
    elif args.publish:
        print(publish_completed(args.job_dir,args.brief,args.call))
    else:
        job=_execution_job(args.job_dir);payload=args.brief.read_bytes()
        if validate_brief(payload)['job_id']!=job.job_id:
            raise ValueError('Sweety frozen request belongs to another Job')
        consume_result(payload,json.loads(args.media_manifest.read_bytes()),args.output)


if __name__=='__main__':
    main()

"""Garden Motion Showreel: hand off creative work to the original Skill and bind its actual silent render."""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, shutil, subprocess, sys
from pathlib import Path
if __file__ == '<stdin>':
    p=argparse.ArgumentParser(add_help=False); p.add_argument('--skill-root', required=True, type=Path)
    SKILL=p.parse_known_args()[0].skill_root.resolve(strict=True)
else:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from package_paths import PACKAGE_ROOT as SKILL
sys.path[:0]=[str(SKILL),str(SKILL/'scripts')]
from adapter_kit import sha256_file as sha, validate_source_binding
from edit.hd.tools import contract_artifacts as artifacts
from motion_native_skill_adapter import relative, path, descriptor, exact, task_source, _inputs, probe
ENTRY='scripts/garden_native_adapter.py'
DEPENDENCY_ID='garden-motion-showreel'
VERSION='1.0.0'
RENDERER_VERSION='garden-2b9a89340b70'
SOURCE_PIN='2b9a89340b70f632d31c0f1c69fce94a7912423e'
PROJECT=SKILL

def source_root(project=SKILL, *, dependency_id=DEPENDENCY_ID):
    from prepare_sources import bundled_source_revision
    from native_result_reuse import source_unchanged
    if dependency_id != DEPENDENCY_ID: raise ValueError('Unknown Garden source')
    project=Path(project).resolve(strict=True); root=project/'vendor/garden-skills'
    if not root.is_dir() or root.resolve()!=root: raise ValueError('Garden complete source missing')
    def verify(_):
        if bundled_source_revision(project,root)!=SOURCE_PIN: raise ValueError('Garden source revision changed')
    return source_unchanged(project,DEPENDENCY_ID,root,verify,records=(project/'archives/sources/index.json',))

def load_template_catalog(project=SKILL, *, dependency_id=DEPENDENCY_ID):
    source_root(project,dependency_id=dependency_id)
    return json.loads((Path(project)/'references/garden-motion-showreel-template-catalog.json').read_bytes())['native_paths']

def _template(b,project=SKILL):
    rows=load_template_catalog(project)
    row=next((r for r in rows if r['template_id']==b['template_id'] or r['template_id']==DEPENDENCY_ID+'/'+b['template_id']),None)
    if not row or row.get('native_template_group')!='style' or b['alpha']:
        raise ValueError('Garden requires an original opaque creative style')
    return row

def check_runtime(project_root=SKILL, mode='reuse', project_directory=None):
    source_root(project_root)
    tools={k:shutil.which(k) for k in ('node','ffmpeg','ffprobe')}
    if not all(tools.values()): raise ValueError('Garden requires Node, ffmpeg and ffprobe')
    v=subprocess.check_output([tools['node'],'--version'],text=True).strip()
    if not re.match(r'v(\d+)',v) or int(re.match(r'v(\d+)',v).group(1))<18: raise ValueError('Garden requires Node 18+')
    if project_directory is not None:
        r=subprocess.run([tools['node'],'-e',"require.resolve('playwright')"],cwd=project_directory,capture_output=True,text=True)
        if r.returncode: raise ValueError('Install upstream Playwright in the isolated native Job project')
    return {'status':'ready','tools':tools,'renderer_version':RENDERER_VERSION}

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
        raise ValueError('Invalid Garden native task brief')
    validate_source_binding(b['source_binding'], 'Invalid Garden speech clock')
    c = b['composition']
    if (type(c) is not dict or set(c) != {'width', 'height', 'fps', 'frames'}
            or any(type(c[k]) is not int for k in c) or (c['width'], c['height'], c['fps']) != (1080, 1920, 24)
            or c['frames'] < 1 or abs((b['source_binding']['end']-b['source_binding']['start'])*24-c['frames']) > 1e-6):
        raise ValueError('Garden requires the exact portrait 24fps parent clock')
    for key in ('job_id', 'template_id', 'semantic_goal', 'transcript'):
        if not isinstance(b[key], str) or not b[key].strip():
            raise ValueError('Garden requires real content and identity')
    task = b['task_source']
    if (type(task) is not dict or set(task) != {'semantic_row_id','quote','semantic','required_change','component_brief'}
            or any(not isinstance(v, str) or not v.strip() for v in task.values())
            or task['semantic'] != b['semantic_goal']):
        raise ValueError('Garden task must derive from its approved semantic row')
    r = b['template_request']
    if (type(r) is not dict or set(r) != {'semantic_family','information_units','numeric_values','numeric_scale'}
            or not isinstance(r['semantic_family'], str) or not r['semantic_family']
            or type(r['information_units']) is not int or r['information_units'] < 1
            or type(r['numeric_values']) is not list
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in r['numeric_values'])
            or r['numeric_scale'] not in ({'linear','log'} if r['numeric_values'] else {'not_applicable'})):
        raise ValueError('Invalid Garden semantic request')
    if not isinstance(b['word_anchors'], list) or not b['word_anchors']:
        raise ValueError('Garden needs the existing real word clock')
    for word in b['word_anchors']:
        if (type(word) is not dict or set(word) != {'text','start','end'}
                or not isinstance(word['text'], str) or not word['text']
                or any(type(word[k]) not in (int,float) or not math.isfinite(word[k]) for k in ('start','end'))
                or not 0 <= word['start'] < word['end'] <= c['frames']/24):
            raise ValueError('Garden word clock must be scene-local and real')
    if not isinstance(b['materials'], list) or not isinstance(b['authorization'], dict):
        raise ValueError('Garden needs actual materials and resource authorization')
    if relative(b['project_directory']).parts[0] != 'native-projects':
        raise ValueError('Garden project belongs in the current Job native-projects directory')
    if relative(b['result_record_path']).parts[0] != 'native-inputs':
        raise ValueError('Garden completion belongs in native-inputs')
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
                raise ValueError('Selected Garden task requires its actual brief')
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
                raise ValueError('Garden selected inputs differ from approved meaning, source or word clock')
            _template(b);_inputs(job.job_dir,b)


def create_adapter(project_root,python_executable,brief_loader,*,renderer_version=None,dependency_id=DEPENDENCY_ID):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter,ReferenceProcessMedia
    source_root(project_root,dependency_id=dependency_id);check_runtime(project_root,mode='reuse')
    if renderer_version not in (None,RENDERER_VERSION):
        raise ValueError('Unknown Garden renderer')
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
            raise ValueError('Garden component differs from its approved Job, input or clock')
        _inputs(job.job_dir,b);return payload
    def media_loader(job,recipe,component,payload):
        from edit.hd.tools.visual_confirmation import native_result_descriptor
        expected=native_result_descriptor(job,recipe['segment_id'],component['component_id'],hashlib.sha256(payload).hexdigest())
        result=load_result(job.job_dir,payload,expected_record=expected)
        return tuple(ReferenceProcessMedia('garden-'+hashlib.sha256(r['job_path'].encode()).hexdigest()[:32],r['job_path'],r['sha256'])
                     for r in [{'job_path':expected['path'],'sha256':expected['sha256']},result['media']])
    return ReferenceProcessAdapter(adapter_id='garden-native-skill-v1',dependency_id=DEPENDENCY_ID,
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
        raise ValueError('Garden frozen request changed')
    rows={r['media_ref']:r for r in manifest['media']}
    def read(name):
        r=rows['garden-'+hashlib.sha256(name.encode()).hexdigest()[:32]]
        data=Path('/dev/fd/'+str(r['fd'])).read_bytes()
        if len(data)!=r['byte_length'] or hashlib.sha256(data).hexdigest()!=r['sha256']:
            raise ValueError('Garden frozen input changed')
        return data
    result=json.loads(read(b['result_record_path']))
    if (result.get('request_sha256')!=hashlib.sha256(payload).hexdigest() or result.get('status')!='completed'
            or result.get('dependency_id')!=DEPENDENCY_ID or result.get('template_id')!=b['template_id']):
        raise ValueError('Garden frozen completion changed')
    video=read(result['media']['job_path'])
    if hashlib.sha256(video).hexdigest()!=result['media']['sha256'] or len(video)!=result['media']['byte_count']:
        raise ValueError('Garden frozen video changed')
    target = Path(output)
    # The parent supplies an already opened output descriptor. Regular sample
    # paths still use exclusive creation so a result is never overwritten.
    mode = 'wb' if re.fullmatch(r'/dev/fd/[0-9]+', str(target)) else 'xb'
    with target.open(mode) as stream:
        stream.write(video)



def native_task(job, recipe, component, brief_path, *, approved_task_source, defer_runtime=False):
    payload=Path(brief_path).read_bytes(); b=validate_brief(payload); row=_template(b)
    if (b['job_id']!=job.job_id or sha(brief_path)!=component['brief_sha256'] or
        any(b['task_source'][k]!=approved_task_source[k] for k in ('semantic_row_id','quote','semantic'))):
        raise ValueError('Garden task changed after selection')
    _inputs(job.job_dir,b)
    runtime={'status':'pending'} if defer_runtime else check_runtime()
    directory=path(job.job_dir,b['project_directory'])
    return {'action':'execute_native_skill','dependency_id':DEPENDENCY_ID,'native_template':row,
        'native_instructions':row['native_instructions'],'native_options':[], 'task_source':b['task_source'],
        'template_id':DEPENDENCY_ID+'/'+b['template_id'],'skill_path':str(SKILL/row['skill_path']),
        'job_dir':str(job.job_dir),'brief_path':str(brief_path),'brief_sha256':sha(brief_path),
        'project_directory':str(directory),'runtime':runtime,'segment_id':recipe['segment_id'],
        'component_id':component['component_id'],'requirements':{**b['composition'],'alpha':False,'silent':True,
        'canvas_transport':'identity','native_captions':False,'semantic_goal':b['semantic_goal'],
        'transcript':b['transcript'],'word_anchors':b['word_anchors'],'authorization':b['authorization']},
        'speech':str(path(job.job_dir,b['speech']['job_path'])),'source_binding':b['source_binding'],
        'materials':[str(path(job.job_dir,m['job_path'])) for m in b['materials']],
        'result_record_path':b['result_record_path'],
        'next':'Read original motion-showreel SKILL.md and selected style instructions. In the isolated Job project scaffold with --audio none; author the scene from the actual task and style, never modify vendor. Set timeline DUR to the exact parent window. Prepare Playwright in this Job project and required scene libraries. Call capture_render then publish_completed. The style is creative guidance, not a fixed preset; review actual visual meaning and design.'}


def project_files(root,directory):
    return [descriptor(root,p) for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
            and p.relative_to(directory).parts[0] not in {'node_modules','out','qa','work','.git'}]


def _commands(root,b,runtime):
    directory=path(root,b['project_directory']).resolve(strict=True)
    if not (directory/'index.html').is_file() or not (directory/'timeline.js').is_file():
        raise ValueError('Garden native Job project requires its authored page and timeline')
    script=source_root()/'skills/motion-showreel/scripts'
    target=directory/'out/native.mp4'
    render=[runtime['tools']['node'],str(script/'render.mjs'),str(directory),'--size','1080x1920','--fps','24','--out',str(target)]
    check=[runtime['tools']['node'],str(script/'inspect.mjs'),'qa',str(target),'--out',str(directory/'qa/native'),
           '--expect-size','1080x1920','--expect-fps','24','--expect-duration',str(b['composition']['frames']/24),'--audio','none']
    return directory,target,render,check


def capture_render(job_dir,brief_path,argv=None,*,native_preparations=None):
    if native_preparations is not None: raise ValueError('Garden Job uses its own project dependencies')
    job=_execution_job(job_dir); root=Path(job_dir).resolve(strict=True)
    brief_path=Path(brief_path).resolve(strict=True); brief_path.relative_to(root)
    payload=brief_path.read_bytes(); b=validate_brief(payload); _inputs(root,b)
    if b['job_id']!=job.job_id: raise ValueError('Garden task belongs to another Job')
    directory=path(root,b['project_directory']).resolve(strict=True)
    runtime=check_runtime(project_directory=directory);directory,target,render,check=_commands(root,b,runtime)
    if argv is not None and argv!=render: raise ValueError('Garden requires its original native render command')
    result_path=path(root,b['result_record_path']);call_path=result_path.with_name(result_path.stem+'.render-call.json')
    if target.exists() or call_path.exists() or result_path.exists(): raise ValueError('Preserve completed Garden results')
    target.parent.mkdir(parents=True,exist_ok=True); before=project_files(root,directory)
    call={'schema_version':1,'status':'running','dependency_id':DEPENDENCY_ID,'request_sha256':sha(brief_path),
          'upstream_commit':SOURCE_PIN,'renderer_version':RENDERER_VERSION,'project_files':before,'steps':[]}
    try:
        for command in (render,check):
            p=subprocess.run(command,cwd=directory,capture_output=True,text=True,timeout=1200)
            call['steps'].append({'argv':command,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
            if p.returncode: raise ValueError('Garden native rendering or QA failed: '+p.stderr[-1500:])
        if probe(target,alpha=False)!=b['composition']: raise ValueError('Garden output clock or format differs')
        if project_files(root,directory)!=before: raise ValueError('Garden authored project changed during rendering')
        source_root();call.update(status='completed',media=descriptor(root,target))
    except BaseException as e:
        call.update(status='failed',error=str(e));raise
    finally:
        artifacts.write_json_artifact(call_path,call)
    return call_path


def _verify_call(root,b,payload,call):
    runtime=check_runtime();directory,target,render,check=_commands(root,b,runtime)
    steps=call.get('steps',[])
    if (call.get('status')!='completed' or call.get('dependency_id')!=DEPENDENCY_ID
        or call.get('request_sha256')!=hashlib.sha256(payload).hexdigest()
        or call.get('upstream_commit')!=SOURCE_PIN or call.get('renderer_version')!=RENDERER_VERSION
        or len(steps)!=2 or [x.get('argv') for x in steps]!=[render,check]
        or any(x.get('exit_code')!=0 for x in steps) or call.get('project_files')!=project_files(root,directory)
        or exact(root,call['media'])!=target.resolve(strict=True) or probe(target,alpha=False)!=b['composition']):
        raise ValueError('Garden result does not match its original completed render and checks')


def publish_completed(job_dir,brief_path,call_path,*,native_usage=None):
    if native_usage is not None: raise ValueError('Garden uses one selected style')
    job=_execution_job(job_dir);payload=Path(brief_path).read_bytes();b=validate_brief(payload);_inputs(job_dir,b)
    if b['job_id']!=job.job_id: raise ValueError('Garden result belongs to another Job')
    call=json.loads(Path(call_path).read_bytes());_verify_call(job_dir,b,payload,call)
    target=path(job_dir,b['result_record_path'])
    if target.exists(): raise ValueError('Preserve completed Garden result')
    artifacts.write_json_artifact(target,{'schema_version':3,'status':'completed','dependency_id':DEPENDENCY_ID,
        'job_id':b['job_id'],'template_id':b['template_id'],'request_sha256':hashlib.sha256(payload).hexdigest(),
        'media':call['media'],'media_probe':b['composition'],'alpha':False,'renderer_version':RENDERER_VERSION,
        'render_call':descriptor(job_dir,call_path),'product_scope':'silent_visual_material',
        'native_captions':False,'subtitle_owner':'parent'})
    return target


def inspect_result(job_dir,payload,*,record_bytes=None):
    b=validate_brief(payload);_inputs(job_dir,b)
    result=json.loads(record_bytes if record_bytes is not None else path(job_dir,b['result_record_path']).read_bytes())
    expected={'schema_version':3,'status':'completed','dependency_id':DEPENDENCY_ID,'job_id':b['job_id'],
        'template_id':b['template_id'],'request_sha256':hashlib.sha256(payload).hexdigest(),
        'media_probe':b['composition'],'alpha':False,'renderer_version':RENDERER_VERSION,
        'product_scope':'silent_visual_material','native_captions':False,'subtitle_owner':'parent'}
    if any(result.get(k)!=v for k,v in expected.items()): raise ValueError('Garden completion changed')
    call=json.loads(exact(job_dir,result['render_call']).read_bytes());_verify_call(job_dir,b,payload,call)
    if result['media']!=call['media']: raise ValueError('Garden output changed')
    return result


def load_result(job_dir,payload,*,expected_record,expected_renderer_version=RENDERER_VERSION):
    b=validate_brief(payload)
    if expected_record.get('path')!=b['result_record_path'] or expected_renderer_version!=RENDERER_VERSION: raise ValueError('Garden result binding changed')
    data=path(job_dir,expected_record['path']).read_bytes()
    if len(data)!=expected_record['bytes'] or hashlib.sha256(data).hexdigest()!=expected_record['sha256']: raise ValueError('Garden result differs from frozen result')
    return inspect_result(job_dir,payload,record_bytes=data)


def main():
    p=argparse.ArgumentParser();p.add_argument('--skill-root',type=Path);p.add_argument('--project-root',type=Path,default=SKILL)
    p.add_argument('--dependency-id',default=DEPENDENCY_ID,choices=[DEPENDENCY_ID]);p.add_argument('--brief',type=Path)
    p.add_argument('--job-dir',type=Path,default=os.environ.get('BROLL_JOB_DIR'));p.add_argument('--capture-render',action='store_true')
    p.add_argument('--argv-json');p.add_argument('--publish',action='store_true');p.add_argument('--call',type=Path)
    p.add_argument('--probe',action='store_true');p.add_argument('--media-manifest',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.probe:
        check_runtime(a.project_root);print(json.dumps({'schema_version':1,'dependency_id':DEPENDENCY_ID,'entrypoint':ENTRY,'producer_version':VERSION,
            'adapter_identity':{'adapter_type':'ReferenceProcessAdapter','approved_executor':'reference_adapter','primary_renderer':'HTMLCanvas'}}))
    elif a.capture_render: print(capture_render(a.job_dir,a.brief,json.loads(a.argv_json) if a.argv_json else None))
    elif a.publish: print(publish_completed(a.job_dir,a.brief,a.call))
    else:
        job=_execution_job(a.job_dir);payload=a.brief.read_bytes()
        if validate_brief(payload)['job_id']!=job.job_id: raise ValueError('Garden frozen request belongs to another Job')
        consume_result(payload,json.loads(a.media_manifest.read_bytes()),a.output)

if __name__=='__main__': main()

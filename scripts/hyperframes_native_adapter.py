"""Freeze Job-owned HTML/bitmap assets and invoke the actual upstream HyperFrames CLI."""
import hashlib,json,math,os,re,shutil,sys,subprocess,tempfile
from pathlib import Path
SKILL=Path(__file__).resolve().parent.parent
ENTRY='scripts/hyperframes_native_adapter.py'
DEPENDENCY_ID='hyperframes-native-adaptation'
VERSION='1.1.0'
ROUTES={
    'paper-collage-ad/hyperframes':'../vendor/paper-collage-ad-codex/references/hyperframes-route.md',
    'hyperframes/hw-pipeline':'registry/blocks/hw-pipeline/hw-pipeline.html',
    'hyperframes/macos-notification':'registry/blocks/macos-notification/macos-notification.html',
    'hyperframes/mk-specs-list':'registry/blocks/mk-specs-list/mk-specs-list.html',
    'hyperframes/strikethrough-replace':'registry/components/strikethrough-replace/strikethrough-replace.html',
    'hyperframes/before-after-wipe':'registry/components/before-after-wipe/before-after-wipe.html',
    'hyperframes/toggle-flip':'registry/components/toggle-flip/toggle-flip.html',
    'hyperframes/notification-stack':'registry/components/notification-stack/notification-stack.html',
    'hyperframes/grid-card-assemble':'registry/components/grid-card-assemble/grid-card-assemble.html',
}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_brief(payload):
    b=json.loads(payload)
    if set(b)!={'schema_version','source_binding','template_request','entry','assets','composition','upstream_route','source_pins'} or b['schema_version']!=2:raise ValueError('Invalid native HTML brief')
    s=b['source_binding'];c=b['composition'];r=b['template_request']
    if set(s)!={'aroll_sha256','segment_id','start','end'} or not re.fullmatch('[a-f0-9]{64}',s['aroll_sha256']) or not 0<=s['start']<s['end']:raise ValueError('Invalid source clock')
    if set(c)!={'width','height','fps','frames','alpha'} or c['width']!=1080 or c['height']!=1920 or c['fps']!=24 or type(c['alpha']) is not bool or c['frames']!=round((s['end']-s['start'])*24) or c['frames']<1 or abs((s['end']-s['start'])*24-c['frames'])>1e-6:raise ValueError('Invalid portrait clock')
    if set(r)!={'semantic_family','information_units','numeric_values','numeric_scale'} or not r['semantic_family'] or r['information_units']<1 or r['numeric_values']!=[] or r['numeric_scale']!='not_applicable':raise ValueError('Native HTML request must be an explanatory nonnumeric scene')
    if b['upstream_route'] not in ROUTES:raise ValueError('Unknown upstream route')
    pins=b['source_pins']
    if set(pins)!={'route','sha256'} or pins['route']!=b['upstream_route'] or not re.fullmatch('[a-f0-9]{64}',pins['sha256']):raise ValueError('Invalid native source pin')
    if len(b['assets'])>4:raise ValueError('Too many scene assets')
    records=[b['entry'],*b['assets']]
    if len({r['media_ref'] for r in records})!=len(records):raise ValueError('Repeated media')
    for record in records:
        p=Path(record['job_path']);dest=Path(record['scene_path'])
        if set(record)!={'media_ref','job_path','scene_path','sha256'} or any(x.is_absolute() or '..' in x.parts for x in (p,dest)) or not re.fullmatch('[a-f0-9]{64}',record['sha256']):raise ValueError('Invalid frozen asset identity')
    if b['entry']['scene_path']!='index.html':raise ValueError('One native HTML entry required')
    return b
def check_runtime(project,executables=None):
    runtime=project/'参考项目/B-roll开源方案/hyperframes'
    pins={project/'skill-development/vendor/paper-collage-ad-codex/references/hyperframes-route.md':'255e9d5d87c3d2ad491c8f6e1d808e6d03f93f36f0efee95a584584a1e41366d',runtime/'registry/blocks/hw-pipeline/hw-pipeline.html':'5f2d91c91d37dd6b57a015a02361c67c9a62ca33849b901b3bebad8157fb7dbb',runtime/'skills/talking-head-recut/assets/vendor/gsap.min.js':'c3a03a345e45bc954cd48c43f11572891f5dca7a5d99348d5bc14753a728618c'}
    if any(sha(p)!=h for p,h in pins.items()) or json.loads((runtime/'packages/cli/package.json').read_bytes())['version']!='0.8.19':raise ValueError('Upstream native HTML runtime changed')
    paths={k:Path(executables[k] if executables else shutil.which(k)).resolve() for k in ('node','ffmpeg','ffprobe')}
    paths['browser']=project/'.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    paths['cli']=runtime/'packages/cli/src/cli.ts';paths['tsx']=runtime/'node_modules/tsx/dist/cli.mjs';paths['gsap']=runtime/'skills/talking-head-recut/assets/vendor/gsap.min.js'
    for route, relative in ROUTES.items():
        source=(project/'skill-development/vendor/paper-collage-ad-codex/references/hyperframes-route.md'
                if route == 'paper-collage-ad/hyperframes' else runtime/relative)
        paths.setdefault('route_sources', {})[route]=source
        if not source.is_file(): raise ValueError('Native source missing: '+route)
    return paths,{k:sha(p) for k,p in paths.items() if k != 'route_sources'}
def create_adapter(project_root,python_executable,brief_loader):
    from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter,ReferenceProcessMedia
    project=Path(project_root).resolve();python=Path(python_executable).resolve();entry_sha=sha(SKILL/ENTRY)
    paths,runtime=check_runtime(project)
    def guard(job,recipe,component):
        from edit.hd.tools import visual_canary
        if check_runtime(project)[1]!=runtime or sha(SKILL/ENTRY)!=entry_sha:raise ValueError('Bound runtime changed')
        payload=brief_loader(job,recipe,component);b=validate_brief(payload)
        plan=visual_canary.load_approved_visual_plan(job);s=next(s for s in plan['segments'] if s['segment_id']==recipe['segment_id'])
        expected=dict(aroll_sha256=plan['edited_aroll_sha256'],segment_id=s['segment_id'],start=s['start'],end=s['end'])
        if s['shot_recipe']!=json.loads(json.dumps(recipe)) or b['source_binding']!=expected or b['template_request']!=json.loads(json.dumps(component['invocation_record']['template_request'])) or component['source_sha256']!=entry_sha or component['artifact_contract']!={'width':1080,'height':1920,'fps':24,'alpha':b['composition']['alpha']} or component['render_window']['end_frame']!=b['composition']['frames']:raise ValueError('Native HTML no longer matches the approved shot')
        return payload
    def media(job,recipe,component,payload):
        b=validate_brief(payload)
        return tuple(ReferenceProcessMedia(media_ref=r['media_ref'],job_path=r['job_path'],sha256=r['sha256']) for r in [b['entry'],*b['assets']])
    return ReferenceProcessAdapter(adapter_id='hyperframes-native-frozen-v1',dependency_id=DEPENDENCY_ID,approved_executor='reference_adapter',dependency_root=SKILL,entrypoint=ENTRY,entrypoint_sha256=entry_sha,producer_version=VERSION,primary_renderer='HyperFrames',renderer_version='0.8.19',artifact_media_type='video',launcher=python,launcher_sha256=sha(python),brief_loader=guard,media_loader=media,self_contained_wrapper=True,timeout_seconds=300,argv_template=('{launcher}','{entrypoint}','--brief','{brief_path}','--media-manifest','{media_manifest_fd}','--project-root',str(project),'--node',str(paths['node']),'--ffmpeg',str(paths['ffmpeg']),'--ffprobe',str(paths['ffprobe']),'--node-sha256',runtime['node'],'--ffmpeg-sha256',runtime['ffmpeg'],'--ffprobe-sha256',runtime['ffprobe'],'--output','{output_path}'))
def create_binding(adapter,payload,sample):
    b=validate_brief(payload);r=b['template_request']
    return dict(producer_type='dependency',dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,primary_renderer='HyperFrames',renderer_version='0.8.19',template_origin='custom_fallback',template_id=b['upstream_route'].replace('/','-')+'-portrait-adaptation',template_version=VERSION,verification_id=hashlib.sha256((adapter.entrypoint_sha256+b['entry']['sha256']).encode()).hexdigest(),adaptation_level='structural',source_entrypoint=ENTRY,source_sha256=adapter.entrypoint_sha256,sample_sha256=sha(sample),semantic_families=[r['semantic_family']],capacity=dict(min_units=r['information_units'],max_units=r['information_units']),brief_sha256=hashlib.sha256(payload).hexdigest(),invocation_record=dict(argv=[str(adapter.launcher),ENTRY],status='planned',exit_code=None,template_request=r))
def render(args):
    payload=Path(args.brief).read_bytes();b=validate_brief(payload);paths,pins=check_runtime(Path(args.project_root),dict(node=args.node,ffmpeg=args.ffmpeg,ffprobe=args.ffprobe))
    if any(pins[k]!=getattr(args,k+'_sha256') for k in ('node','ffmpeg','ffprobe')):raise ValueError('Bound renderer executables changed')
    if sha(paths['route_sources'][b['upstream_route']])!=b['source_pins']['sha256']:raise ValueError('Native source pin changed')
    frozen=json.loads(Path(args.media_manifest).read_bytes())
    if frozen['schema_version']!='reference-process-media/v1' or frozen['brief_sha256']!=hashlib.sha256(payload).hexdigest():raise ValueError('Wrong frozen request')
    records={r['media_ref']:r for r in frozen['media']};expected=[b['entry'],*b['assets']]
    if set(records)!={r['media_ref'] for r in expected}:raise ValueError('Wrong media set')
    with tempfile.TemporaryDirectory(prefix='hd-native-hf-') as temp:
        d=Path(temp);(d/'vendor').mkdir();shutil.copyfile(paths['gsap'],d/'vendor/gsap.min.js')
        for r in expected:
            f=records[r['media_ref']];data=Path('/dev/fd/'+str(f['fd'])).read_bytes()
            if hashlib.sha256(data).hexdigest()!=r['sha256'] or f['sha256']!=r['sha256'] or len(data)!=f['byte_length']:raise ValueError('Frozen media changed')
            if r['media_ref']=='entry':
                text=data.decode();urls=re.findall(r'(?:src|url)\s*(?:=|\()\s*[\"\x27]?([^\"\x27)\s>]+)',text)
                allowed={'vendor/gsap.min.js',*[x['scene_path'] for x in b['assets']]}
                if any(u not in allowed for u in urls) or re.search(r'fetch\s*\(|https?://|<audio|<video|@import',text.replace('http://www.w3.org/2000/svg','')):raise ValueError('Native entry must use only frozen local assets and no audio/network')
            p=d/r['scene_path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        native=d/('native.mov' if b['composition']['alpha'] else 'native.mp4');target=d/('target.mov' if b['composition']['alpha'] else 'target.mp4')
        output_format='mov' if b['composition']['alpha'] else 'mp4'
        argv=[str(paths['node']),str(paths['tsx']),str(paths['cli']),'render',str(d),'--composition','index.html','--output',str(native),'--format',output_format,'--fps','24','--quality','high','--workers','1','--low-memory-mode','--no-browser-gpu','--no-best-effort','--quiet']
        env={**os.environ,'PATH':str(paths['ffmpeg'].parent)+os.pathsep+str(paths['node'].parent)+os.pathsep+'/usr/bin:/bin','HYPERFRAMES_BROWSER_PATH':str(paths['browser']),'HYPERFRAMES_NO_TELEMETRY':'1','DO_NOT_TRACK':'1'}
        r=subprocess.run(argv,capture_output=True,timeout=240,env=env)
        if r.returncode:raise RuntimeError(r.stderr.decode()[-2000:])
        ffmpeg_args=[str(paths['ffmpeg']),'-v','error','-i',str(native),'-map','0:v:0','-an']
        ffmpeg_args += ['-vf','setsar=1','-c:v','qtrle','-pix_fmt','argb'] if b['composition']['alpha'] else ['-c:v','copy','-bsf:v','h264_metadata=sample_aspect_ratio=1/1']
        ffmpeg_args += [str(target)]
        subprocess.run(ffmpeg_args,check=True,capture_output=True)
        s=json.loads(subprocess.check_output([str(paths['ffprobe']),'-v','error','-show_streams','-of','json',str(target)]))['streams']
        if len(s)!=1 or (s[0]['width'],s[0]['height'],s[0]['avg_frame_rate'],s[0]['sample_aspect_ratio'],int(s[0]['nb_frames']))!=(1080,1920,'24/1','1:1',b['composition']['frames']) or (b['composition']['alpha'] and (s[0].get('codec_name')!='qtrle' or s[0].get('pix_fmt')!='argb')):raise ValueError('Native output clock or alpha changed')
        data=target.read_bytes();Path(args.output).write_bytes(data)
        return dict(upstream_route=b['upstream_route'],upstream_argv=argv,exit_code=r.returncode,runtime_sha256=pins,output_sha256=hashlib.sha256(data).hexdigest(),frames=b['composition']['frames'],external_requests=0,normalization='alpha=qtrle/argb, audio=removed, sar=1:1' if b['composition']['alpha'] else 'SAR metadata only')
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--project-root',required=True);p.add_argument('--brief');p.add_argument('--media-manifest');[p.add_argument('--'+k) for k in ('node','ffmpeg','ffprobe','node-sha256','ffmpeg-sha256','ffprobe-sha256')];p.add_argument('--output');a=p.parse_args()
    if a.brief:print(json.dumps(render(a)))
    else:
        sys.path.insert(0,a.project_root);adapter=create_adapter(a.project_root,sys.executable,lambda *_:b'')
        print(json.dumps(dict(schema_version=1,dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,adapter_identity=dict(adapter_type='ReferenceProcessAdapter',approved_executor='reference_adapter',primary_renderer='HyperFrames'))))

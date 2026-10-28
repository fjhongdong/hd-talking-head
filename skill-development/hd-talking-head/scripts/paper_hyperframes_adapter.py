"""Hand off the complete native Paper Skill; freeze and render its Route B output.

The original Skill owns concept, scene, layout and GSAP choreography. This bridge
only passes source facts and delivery parameters, then enforces file identities,
the approved clock and the existing reference-process renderer boundary.
"""
import argparse,hashlib,json,sys,tempfile,subprocess,math,re,shutil
from pathlib import Path
from types import SimpleNamespace
hf=None; check_motion=None; ENTRY_PATH=None; SKILL=Path(__file__).resolve().parents[1] if __file__!='<stdin>' else None
ENTRY='scripts/paper_hyperframes_adapter.py'; DEPENDENCY_ID='paper-collage-hyperframes'; VERSION='2.0.0'; ROUTE='paper-collage-ad/hyperframes'
SHARED_SHA='881645ecf51092e9cf2f429ba268c001d1ca106b88a01f0074e240c41a408f44'
UPSTREAM_COMMIT='a69c9f56eec57ca19d1c02f6bdcffe573b4324a8'
READ_FILES=('SKILL.md','references/hyperframes-route.md','references/collage-dimensions.md','references/prompt-patterns.md','references/production-workflow.md','references/dependencies.md','examples/hyperframes-logo-composition.html')
def _ensure(project,skill_root=None):
 global hf,check_motion,ENTRY_PATH,SKILL
 sys.path.insert(0,str(Path(project).resolve()))
 scripts=(Path(skill_root).resolve() if skill_root else Path(project).resolve()/'skill-development/hd-talking-head')/'scripts'
 if str(scripts) not in sys.path: sys.path.insert(0,str(scripts))
 import hyperframes_native_adapter as _hf
 from paper_motion_guard import check as _check
 hf,check_motion=_hf,_check
 ENTRY_PATH=scripts/'paper_hyperframes_adapter.py'; SKILL=scripts.parent

def source_root(project_root):
 from prepare_sources import bundled_source_revision
 project=Path(project_root).resolve(strict=True)
 root=project/'skill-development/vendor/paper-collage-ad-codex'
 if root.is_symlink() or not root.is_dir(): raise ValueError('Complete pinned native Paper Skill is required')
 if (root/'.git').exists():
  head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
  dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip()
  if head!=UPSTREAM_COMMIT or dirty: raise ValueError('Native Paper source changed; do not repair or reset it')
 elif bundled_source_revision(project,root)!=UPSTREAM_COMMIT:
  raise ValueError('Complete pinned native Paper Skill is required')
 return root

def validate_brief(payload):
 if hf is None: _ensure(SKILL.parents[1],SKILL)
 b=hf.validate_brief(payload)
 if b['upstream_route']!=ROUTE or b['composition']['alpha']:
  raise ValueError('Paper requires its opaque native Route B')
 if not b['assets']:
  raise ValueError('Native Paper Route B needs real paper bitmap assets')
 if not any(Path(a['scene_path']).suffix.lower() in {'.png','.jpg','.jpeg','.webp'} for a in b['assets']):
  raise ValueError('Native Paper Route B needs real paper bitmap assets')
 return b

def authoring_context(project_root, *, output_directory, source_binding, composition,
                      template_request, transcript, semantic_goal, assets, speech, word_anchors, authorization,
                      parent_subtitle_layout=None):
 """Dispatch complete upstream creation before HTML/brief freezing.

 Only source facts, clock, available assets and destination cross this boundary.
 The native Skill owns concept, layout, paper staging and GSAP choreography.
 """
 _ensure(project_root)
 root=source_root(project_root)
 output=Path(output_directory).resolve()
 if output.exists() and any(output.iterdir()):
  raise ValueError('Native Paper authoring needs a fresh output directory; preserve previous work')
 if not isinstance(transcript,str) or not transcript.strip() or not isinstance(semantic_goal,str) or not semantic_goal.strip():
  raise ValueError('Native Paper authoring needs approved speech and a semantic goal')
 if (type(source_binding) is not dict or set(source_binding)!={'aroll_sha256','segment_id','start','end'}
     or not re.fullmatch('[a-f0-9]{64}',str(source_binding['aroll_sha256']))
     or not re.fullmatch('seg-[A-Za-z0-9_-]+',str(source_binding['segment_id']))
     or any(type(source_binding[k]) not in (int,float) or not math.isfinite(source_binding[k]) for k in ('start','end'))
     or not 0<=source_binding['start']<source_binding['end']):
  raise ValueError('Native Paper authoring needs its approved source clock')
 if (type(composition) is not dict or any(type(composition.get(k)) is not int for k in ('width','height','fps','frames'))
     or abs((source_binding['end']-source_binding['start'])*24-round((source_binding['end']-source_binding['start'])*24))>1e-6
     or composition!={'width':1080,'height':1920,'fps':24,'frames':round((source_binding['end']-source_binding['start'])*24),'alpha':False}):
  raise ValueError('Native Paper authoring must match the portrait source clock')
 if (type(template_request) is not dict or set(template_request)!={'semantic_family','information_units','numeric_values','numeric_scale'}
     or not isinstance(template_request['semantic_family'],str) or not template_request['semantic_family'].strip()
     or type(template_request['information_units']) is not int or template_request['information_units']<1
     or template_request['numeric_values']!=[] or template_request['numeric_scale']!='not_applicable'):
  raise ValueError('Paper uses the current explanatory nonnumeric request contract')
 duration=composition['frames']/composition['fps']
 if (type(authorization) is not dict or authorization.get('paid_generation') is not False
     or any(type(key) is not str for key in authorization)):
  raise ValueError('Paper Route B requires existing local assets and authorization.paid_generation=false')
 try: json.dumps(authorization,allow_nan=False)
 except (TypeError,ValueError) as error:
  raise ValueError('Paper authorization must retain the normal parent JSON object') from error
 if type(word_anchors) is not list:
  raise ValueError('Paper word anchors must be a local-time list')
 previous_start=-1
 for word in word_anchors:
  if (type(word) is not dict or set(word)!={'text','start','end'}
      or type(word['text']) is not str or not word['text'].strip()
      or any(type(word[k]) not in (int,float) or not math.isfinite(word[k]) for k in ('start','end'))
      or not 0<=word['start']<word['end']<=duration or word['start']<previous_start):
   raise ValueError('Paper word anchors must retain ordered real words inside 0-duration')
  previous_start=word['start']
 if speech is None:
  if word_anchors or parent_subtitle_layout is not None:
   raise ValueError('A silent standalone Paper sample has no parent speech, word anchors or subtitles')
 else:
  if (type(speech) is not dict or set(speech)!={'path','sha256'}
      or type(speech['path']) is not str or not Path(speech['path']).is_absolute()
      or type(speech['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',speech['sha256'])):
   raise ValueError('Paper speech needs an absolute local audio path and its actual SHA256')
  try: audio=Path(speech['path']).resolve(strict=True)
  except OSError as error: raise ValueError('Paper local speech path is missing') from error
  if not audio.is_file() or hf.sha(audio)!=speech['sha256']:
   raise ValueError('Paper local speech identity changed')
  probe=shutil.which('ffprobe')
  if not probe: raise ValueError('Paper local speech needs the existing ffprobe')
  try:
   measured=json.loads(subprocess.check_output([probe,'-v','error','-show_streams','-show_format','-of','json',str(audio)],timeout=30))
   streams=measured['streams']
   measured_duration=float(measured.get('format',{}).get('duration',streams[0].get('duration',0)))
  except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError) as error:
   raise ValueError('Paper local speech cannot be inspected as real audio') from error
  if (len(streams)!=1 or streams[0].get('codec_type')!='audio' or not math.isfinite(measured_duration)
      or abs(measured_duration-duration)>1/composition['fps'] or not word_anchors):
   raise ValueError('Paper needs the actual segment-length audio and its local word anchors')
  if (type(parent_subtitle_layout) is not dict or set(parent_subtitle_layout)!={'safe_zones','placement'}
      or type(parent_subtitle_layout['placement']) is not str
      or parent_subtitle_layout['placement'] not in {'standard','above_avatar'}
      or type(parent_subtitle_layout['safe_zones']) is not dict
      or set(parent_subtitle_layout['safe_zones'])!={'face','subtitle','source','chart'}
      or parent_subtitle_layout['safe_zones']['subtitle'] is None):
   raise ValueError('Paper parent speech requires the actual parent subtitle layout')
  for zone in parent_subtitle_layout['safe_zones'].values():
   if zone is None: continue
   if (type(zone) is not dict or set(zone)!={'x','y','width','height'}
       or any(type(zone[k]) not in (int,float) or not math.isfinite(zone[k]) for k in zone)
       or zone['x']<0 or zone['y']<0 or zone['width']<=0 or zone['height']<=0
       or zone['x']+zone['width']>composition['width'] or zone['y']+zone['height']>composition['height']):
    raise ValueError('Paper parent subtitle regions must be actual rectangles inside the frame')
  speech={'path':str(audio),'sha256':speech['sha256']}
 available=[]
 for item in assets:
  file=Path(item).resolve(strict=True)
  if not file.is_file(): raise ValueError('Paper source asset is not a file')
  available.append({'path':str(file),'sha256':hf.sha(file)})
 if not available: raise ValueError('Native Paper Route B needs available authorized paper assets')
 return {'action':'execute_native_skill','phase':'prepare_template_inputs','dependency_id':DEPENDENCY_ID,
         'template_id':ROUTE,'skill_path':str(root/'SKILL.md'),'upstream_commit':UPSTREAM_COMMIT,
         'read_files':[{'path':str(root/name),'sha256':hf.sha(root/name)} for name in READ_FILES],
         'preflight_argv':['bash',str(root/'scripts/check-deps.sh')],
         'route':'Route B','route_reference':str(root/'references/hyperframes-route.md'),
         'working_directory':str(output),'output_directory':str(output),
         'requirements':{'source_binding':source_binding,'composition':composition,
                         'template_request':template_request,'transcript':transcript,
                         'semantic_goal':semantic_goal,'silent':True,'assets':available,
                         'parent_subtitle_layout':parent_subtitle_layout,'speech':speech,
                         'word_anchors':word_anchors,'authorization':authorization},
         'next':'Read the complete original SKILL.md and its applicable references, then execute its native Route B. The native Skill owns the complete creative scene and HTML/GSAP. Use authorized real paper assets. Preserve approved words, source facts and timing. Supply original editable HTML and all local assets, then freeze a schema_version=2 brief for this bridge. Use existing HyperFrames CLI via this bridge for rendering and record its real argv/result. Do not substitute layer-animate.mjs or flattened-image movement for Route B. Do not modify upstream files or existing movies. Listen to the supplied local speech and use its real local word anchors and parent subtitle regions when present. Parent adds the original speech/subtitles after accepting the silent B-roll; do not synthesize narration or music. authorization is the existing parent object and never widens its scope. This Route B bridge accepts paid_generation=false and existing local assets only; any newly approved generation must first run through the parent frozen generation plan/queue with its approved model and count, then supply its local result as an asset.'}

def native_task(job,recipe,component,brief_path):
 """Describe the complete native Skill for an already approved frozen scene."""
 project=SKILL.parents[1]
 _ensure(project,SKILL)
 root=source_root(project)
 payload=Path(brief_path).read_bytes(); b=validate_brief(payload)
 if hf.sha(brief_path)!=component['brief_sha256'] or recipe['segment_id']!=b['source_binding']['segment_id']:
  raise ValueError('Paper handoff differs from the confirmed component')
 return {'action':'execute_native_skill','dependency_id':DEPENDENCY_ID,'template_id':ROUTE,
         'skill_path':str(root/'SKILL.md'),'upstream_commit':UPSTREAM_COMMIT,
         'read_files':[{'path':str(root/name),'sha256':hf.sha(root/name)} for name in READ_FILES],
         'route':'Route B','job_dir':str(job.job_dir),'brief_path':str(brief_path),
         'brief_sha256':component['brief_sha256'],'segment_id':recipe['segment_id'],
         'component_id':component['component_id'],'requirements':b,
         'next':'The approved HTML/assets are frozen. Execute native Route B through this bridge and the existing reference_adapter. Preserve these inputs. Changes require a new prepared draft and normal visual confirmation; never regenerate or rewrite the approved scene during rendering.'}

def create_adapter(project_root,python_executable,brief_loader):
 _ensure(project_root)
 from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter,ReferenceProcessMedia
 project=Path(project_root).resolve(); _ensure(project); source_root(project); launcher=Path(python_executable).resolve(); paths,runtime=hf.check_runtime(project); entry_sha=hf.sha(ENTRY_PATH); shared_sha=hf.sha(Path(hf.__file__))
 if shared_sha!=SHARED_SHA: raise ValueError('Shared HyperFrames runtime changed')
 def guard(job,recipe,component):
  if hf.sha(ENTRY_PATH)!=entry_sha or hf.sha(Path(hf.__file__))!=shared_sha: raise ValueError('Paper HyperFrames runtime changed')
  source_root(project)
  if hf.check_runtime(project)[1]!=runtime: raise ValueError('Paper HyperFrames runtime changed')
  payload=brief_loader(job,recipe,component); b=validate_brief(payload)
  if b['upstream_route']!=ROUTE or b['composition']['alpha'] or component.get('source_sha256')!=entry_sha: raise ValueError('Paper HyperFrames source identity changed')
  plan=__import__('edit.hd.tools.visual_canary',fromlist=['load_approved_visual_plan']).load_approved_visual_plan(job); seg=next(x for x in plan['segments'] if x['segment_id']==recipe['segment_id'])
  expected=dict(aroll_sha256=plan['edited_aroll_sha256'],segment_id=seg['segment_id'],start=seg['start'],end=seg['end'])
  if seg['shot_recipe']!=json.loads(json.dumps(recipe)) or b['source_binding']!=expected or b['template_request']!=json.loads(json.dumps(component['invocation_record']['template_request'])) or component['artifact_contract']!={'width':1080,'height':1920,'fps':24,'alpha':False} or component['render_window']['end_frame']!=b['composition']['frames']: raise ValueError('Paper HyperFrames no longer matches the approved shot')
  return payload
 def media(job,recipe,component,payload):
  b=validate_brief(payload); return tuple(ReferenceProcessMedia(media_ref=r['media_ref'],job_path=r['job_path'],sha256=r['sha256']) for r in [b['entry'],*b['assets']])
 return ReferenceProcessAdapter(adapter_id='paper-hyperframes-frozen-v1',dependency_id=DEPENDENCY_ID,approved_executor='reference_adapter',dependency_root=SKILL,entrypoint=ENTRY,entrypoint_sha256=entry_sha,producer_version=VERSION,primary_renderer='HyperFrames',renderer_version=hf.RUNTIME_VERSION,artifact_media_type='video',launcher=launcher,launcher_sha256=hf.sha(launcher),brief_loader=guard,media_loader=media,self_contained_wrapper=True,timeout_seconds=300,argv_template=('{launcher}','{entrypoint}','--brief','{brief_path}','--media-manifest','{media_manifest_fd}','--skill-root',str(SKILL),'--shared-sha256',shared_sha,'--project-root',str(project),'--node',str(paths['node']),'--ffmpeg',str(paths['ffmpeg']),'--ffprobe',str(paths['ffprobe']),'--node-sha256',runtime['node'],'--ffmpeg-sha256',runtime['ffmpeg'],'--ffprobe-sha256',runtime['ffprobe'],'--output','{output_path}'))
def create_artifact_probe(ffprobe_executable):
 if hf is None: _ensure(SKILL.parents[1],SKILL)
 return hf.create_artifact_probe(ffprobe_executable)

def create_binding(adapter,payload,sample):
 b=validate_brief(payload)
 if b['upstream_route']!=ROUTE or b['composition']['alpha']: raise ValueError('Paper HyperFrames requires the non-alpha paper route')
 out=hf.create_binding(adapter,payload,sample); out.update(dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,source_entrypoint=ENTRY,source_sha256=adapter.entrypoint_sha256); out['template_version']=VERSION; out['invocation_record']['argv']=[str(adapter.launcher),ENTRY]; return out
def render(args):
 _ensure(Path(args.project_root),args.skill_root); source_root(args.project_root)
 with tempfile.TemporaryDirectory(prefix='paper-hf-') as d:
  if args.shared_sha256!=SHARED_SHA or hf.sha(Path(hf.__file__))!=args.shared_sha256: raise ValueError('Shared HyperFrames runtime changed')
  payload=Path(args.brief).read_bytes(); b=validate_brief(payload)
  if b['upstream_route']!=ROUTE or b['composition']['alpha']: raise ValueError('Paper HyperFrames requires the non-alpha paper route')
  private=Path(d)/'native.mp4'; frozen_brief=Path(d)/'brief.json'; frozen_brief.write_bytes(payload); delegated=SimpleNamespace(**vars(args)); delegated.brief=str(frozen_brief); delegated.output=str(private); result=hf.render(delegated); evidence=check_motion(private,args.ffmpeg,args.ffprobe); data=private.read_bytes(); Path(args.output).write_bytes(data); result.update(dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,upstream_commit=UPSTREAM_COMMIT,native_skill='SKILL.md',native_route='references/hyperframes-route.md',shared_adapter_sha256=args.shared_sha256,motion_guard=evidence,output_sha256=hashlib.sha256(data).hexdigest()); return result
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--skill-root',type=Path); p.add_argument('--shared-sha256'); p.add_argument('--authoring-request',type=Path); p.add_argument('--project-root',required=True); p.add_argument('--brief'); p.add_argument('--media-manifest'); p.add_argument('--output'); [p.add_argument('--'+k) for k in ('node','ffmpeg','ffprobe','node-sha256','ffmpeg-sha256','ffprobe-sha256')]; a=p.parse_args()
 if a.authoring_request:
  print(json.dumps(authoring_context(a.project_root,**json.loads(a.authoring_request.read_bytes())),ensure_ascii=False))
 elif a.brief:
  if not all(getattr(a,k) for k in ('skill_root','shared_sha256','media_manifest','output','node','ffmpeg','ffprobe','node_sha256','ffmpeg_sha256','ffprobe_sha256')): p.error('render requires all dependency arguments')
  print(json.dumps(render(a),ensure_ascii=False))
 else: _ensure(a.project_root,a.skill_root); adapter=create_adapter(a.project_root,sys.executable,lambda *_:b''); print(json.dumps(dict(schema_version=1,dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,adapter_identity=dict(adapter_type='ReferenceProcessAdapter',approved_executor='reference_adapter',primary_renderer='HyperFrames'))))

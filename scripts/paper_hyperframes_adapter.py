"""Paper-only HyperFrames adapter with a motion gate."""
import hashlib,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
hf=None; check_motion=None; ENTRY_PATH=None; SKILL=None
ENTRY='scripts/paper_hyperframes_adapter.py'; DEPENDENCY_ID='paper-collage-hyperframes'; VERSION='1.0.0'; ROUTE='paper-collage-ad/hyperframes'; SHARED_SHA='9a659897e0608b2a108c1e0fa365e4c18f1d79e5dba7ced18aabd7e923bb2edb'
def _ensure(project):
 global hf,check_motion,ENTRY_PATH,SKILL
 scripts=Path(project).resolve()/'skill-development/hd-talking-head/scripts'
 if str(scripts) not in sys.path: sys.path.insert(0,str(scripts))
 import hyperframes_native_adapter as _hf
 from paper_motion_guard import check as _check
 hf,check_motion=_hf,_check
 ENTRY_PATH=scripts/'paper_hyperframes_adapter.py'; SKILL=scripts.parent
def create_adapter(project_root,python_executable,brief_loader):
 from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter,ReferenceProcessMedia
 project=Path(project_root).resolve(); _ensure(project); launcher=Path(python_executable).resolve(); paths,runtime=hf.check_runtime(project); entry_sha=hf.sha(ENTRY_PATH)
 def guard(job,recipe,component):
  if hf.sha(ENTRY_PATH)!=entry_sha or hf.sha(Path(hf.__file__))!=SHARED_SHA: raise ValueError('Paper HyperFrames runtime changed')
  payload=brief_loader(job,recipe,component); b=hf.validate_brief(payload)
  if b['upstream_route']!=ROUTE or b['composition']['alpha'] or component.get('source_sha256')!=entry_sha: raise ValueError('Paper HyperFrames source identity changed')
  plan=__import__('edit.hd.tools.visual_canary',fromlist=['load_approved_visual_plan']).load_approved_visual_plan(job); seg=next(x for x in plan['segments'] if x['segment_id']==recipe['segment_id'])
  expected=dict(aroll_sha256=plan['edited_aroll_sha256'],segment_id=seg['segment_id'],start=seg['start'],end=seg['end'])
  if seg['shot_recipe']!=json.loads(json.dumps(recipe)) or b['source_binding']!=expected or b['template_request']!=json.loads(json.dumps(component['invocation_record']['template_request'])) or component['artifact_contract']!={'width':1080,'height':1920,'fps':24,'alpha':False} or component['render_window']['end_frame']!=b['composition']['frames']: raise ValueError('Paper HyperFrames no longer matches the approved shot')
  return payload
 def media(job,recipe,component,payload):
  b=hf.validate_brief(payload); return tuple(ReferenceProcessMedia(media_ref=r['media_ref'],job_path=r['job_path'],sha256=r['sha256']) for r in [b['entry'],*b['assets']])
 return ReferenceProcessAdapter(adapter_id='paper-hyperframes-frozen-v1',dependency_id=DEPENDENCY_ID,approved_executor='reference_adapter',dependency_root=SKILL,entrypoint=ENTRY,entrypoint_sha256=entry_sha,producer_version=VERSION,primary_renderer='HyperFrames',renderer_version='0.8.19',artifact_media_type='video',launcher=launcher,launcher_sha256=hf.sha(launcher),brief_loader=guard,media_loader=media,self_contained_wrapper=True,timeout_seconds=300,argv_template=('{launcher}','{entrypoint}','--brief','{brief_path}','--media-manifest','{media_manifest_fd}','--project-root',str(project),'--node',str(paths['node']),'--ffmpeg',str(paths['ffmpeg']),'--ffprobe',str(paths['ffprobe']),'--node-sha256',runtime['node'],'--ffmpeg-sha256',runtime['ffmpeg'],'--ffprobe-sha256',runtime['ffprobe'],'--output','{output_path}'))
def create_binding(adapter,payload,sample):
 b=hf.validate_brief(payload)
 if b['upstream_route']!=ROUTE or b['composition']['alpha']: raise ValueError('Paper HyperFrames requires the non-alpha paper route')
 out=hf.create_binding(adapter,payload,sample); out.update(dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,source_entrypoint=ENTRY,source_sha256=adapter.entrypoint_sha256); out['template_version']=VERSION; out['invocation_record']['argv']=[str(adapter.launcher),ENTRY]; return out
def render(args):
 _ensure(Path(args.project_root))
 with tempfile.TemporaryDirectory(prefix='paper-hf-') as d:
  if hf.sha(Path(hf.__file__))!=SHARED_SHA: raise ValueError('Shared HyperFrames runtime changed')
  payload=Path(args.brief).read_bytes(); b=hf.validate_brief(payload)
  if b['upstream_route']!=ROUTE or b['composition']['alpha']: raise ValueError('Paper HyperFrames requires the non-alpha paper route')
  private=Path(d)/'native.mp4'; frozen_brief=Path(d)/'brief.json'; frozen_brief.write_bytes(payload); delegated=SimpleNamespace(**vars(args)); delegated.brief=str(frozen_brief); delegated.output=str(private); result=hf.render(delegated); evidence=check_motion(private,args.ffmpeg,args.ffprobe); data=private.read_bytes(); Path(args.output).write_bytes(data); result.update(dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,motion_guard=evidence,output_sha256=hashlib.sha256(data).hexdigest()); return result
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--brief'); p.add_argument('--media-manifest'); p.add_argument('--output'); [p.add_argument('--'+k) for k in ('node','ffmpeg','ffprobe','node-sha256','ffmpeg-sha256','ffprobe-sha256')]; a=p.parse_args()
 if a.brief:
  if not all(getattr(a,k) for k in ('media_manifest','output','node','ffmpeg','ffprobe','node_sha256','ffmpeg_sha256','ffprobe_sha256')): p.error('render requires all dependency arguments')
  print(json.dumps(render(a),ensure_ascii=False))
 else: _ensure(a.project_root); adapter=create_adapter(a.project_root,sys.executable,lambda *_:b''); print(json.dumps(dict(schema_version=1,dependency_id=DEPENDENCY_ID,entrypoint=ENTRY,producer_version=VERSION,adapter_identity=dict(adapter_type='ReferenceProcessAdapter',approved_executor='reference_adapter',primary_renderer='HyperFrames'))))

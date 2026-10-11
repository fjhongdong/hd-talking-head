"""Binding for the unmodified Wise native continuous-tracking component."""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, shutil
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]; ENTRY="scripts/render_wise_motion.mjs"; DEPENDENCY_ID="wise-motion"; VERSION="3.0.0"; PACKAGE_VERSION="0.1.12"; FPS=24
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_brief(payload):
 b=json.loads(payload); req={"schema_version","source_binding","template_request","composition","theme","title","context_labels","layers"}
 if type(b) is not dict or set(b)!=req or b["schema_version"]!=1 or b["theme"]!="light": raise ValueError("Invalid Wise brief")
 s,c,r=b["source_binding"],b["composition"],b["template_request"]
 if type(s) is not dict or set(s)!={"aroll_sha256","segment_id","start","end"} or not re.fullmatch(r"[a-f0-9]{64}",str(s["aroll_sha256"])) or not re.fullmatch(r"seg-[A-Za-z0-9_-]+",str(s["segment_id"])) or any(type(s[k]) not in (int,float) or not math.isfinite(s[k]) for k in ("start","end")) or not 0<=s["start"]<s["end"]: raise ValueError("Invalid source binding")
 if r!={"semantic_family":"continuous_tracking","information_units":3,"numeric_values":[],"numeric_scale":"not_applicable"}: raise ValueError("Invalid template request")
 if type(c) is not dict or set(c)!={"id","width","height","fps","frames"} or not re.fullmatch(r"[A-Za-z0-9_-]+",str(c["id"])) or any(type(c[k]) is not int or c[k]!=v for k,v in (("width",1080),("height",1920),("fps",FPS))) or type(c["frames"]) is not int: raise ValueError("Invalid composition")
 if type(b["title"]) is not str or not b["title"].strip() or len(b["title"])>10 or any(ord(z)<32 for z in b["title"]): raise ValueError("Invalid tracking title")
 labels=b["context_labels"]
 if type(labels) is not list or len(labels)!=3 or any(type(x) is not str or not x.strip() or len(x)>8 or any(ord(z)<32 for z in x) for x in labels): raise ValueError("Invalid context labels")
 layers=b["layers"]
 if type(layers) is not list or len(layers)!=1: raise ValueError("Use one native tracking layer")
 for x in layers:
  if type(x) is not dict or set(x)!={"id","content","speed","from","layout","transparent"} or x["id"]!="orbit" or type(x["content"]) is not dict or x["content"]!={} or type(x["speed"]) not in (int,float) or not math.isfinite(x["speed"]) or not .5<=x["speed"]<=2 or type(x["from"]) is not int or x["from"]!=0 or x["transparent"] is not False: raise ValueError("Invalid native orbit layer")
  l=x["layout"]
  if type(l) is not dict or set(l)!={"x","y","width","height"} or any(type(v) not in (int,float) or not math.isfinite(v) for v in l.values()) or l["width"]<=0 or l["height"]<=0 or abs(l["width"]/l["height"]-640/360)>1e-6 or min(l["x"],l["y"])<0 or l["x"]+l["width"]>1080 or l["y"]+l["height"]>1920: raise ValueError("Invalid layout")
 # A native continuous loop runs for the voice window; it is not padded footage.
 if c["frames"]<=0 or abs((s["end"]-s["start"])*FPS-c["frames"])>1e-6: raise ValueError("Composition clock mismatch")
 return b
def check_runtime(project_root):
 project=Path(project_root).resolve(strict=True); runtime=project/"skill-development/runtime/wise-motion"
 for name,version in {"wise-motion":PACKAGE_VERSION,"remotion":"4.0.532","@remotion/bundler":"4.0.532","@remotion/renderer":"4.0.532","react":"19.3.0","react-dom":"19.3.0"}.items():
  if json.loads((runtime/"node_modules"/name/"package.json").read_bytes())["version"]!=version: raise ValueError(f"Wise runtime requires exactly {name}@{version}")
 browser=project/".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell"
 if not browser.is_file() or not os.access(browser,os.X_OK): raise ValueError("Project render browser unavailable")
 files=[runtime/"package-lock.json",runtime/"node_modules/wise-motion/dist/index.mjs",runtime/"node_modules/wise-motion/ASSET-MANIFEST.json",runtime/"public/wise-motion/.wise-motion-assets.json",SKILL/"assets/wise-motion-runtime/index.jsx",browser]
 return {"path":str(runtime),"browser":str(browser),"identity":hashlib.sha256(b"\0".join(p.read_bytes() for p in files)).hexdigest()}
def prepare_runtime(project_root):
 project=Path(project_root).resolve(strict=True); runtime=project/"skill-development/runtime/wise-motion"
 if runtime.is_symlink() or not runtime.resolve().is_relative_to(project): raise ValueError("Wise runtime must stay inside the project")
 runtime.mkdir(parents=True,exist_ok=True)
 for name in ("package.json","package-lock.json"):
  src=SKILL/"assets/wise-motion-runtime"/name; dst=runtime/name
  if dst.exists() and dst.read_bytes()!=src.read_bytes(): raise ValueError("Existing Wise dependency configuration differs")
  if not dst.exists(): shutil.copyfile(src,dst)
 if not (runtime/"node_modules/wise-motion/dist/index.mjs").is_file():
  import subprocess; subprocess.run(["npm","ci","--ignore-scripts","--no-audit","--no-fund"],cwd=runtime,check=True,timeout=240)
 if not (runtime/"public/wise-motion/.wise-motion-assets.json").is_file():
  import subprocess; subprocess.run(["node",str(runtime/"node_modules/wise-motion/scripts/install-assets.mjs"),str(runtime/"public/wise-motion")],cwd=runtime,check=True,timeout=120)
 return check_runtime(project)
def create_adapter(project_root,node_executable,brief_loader):
 from edit.hd.tools.broll_component_executor import ReferenceProcessAdapter
 project=Path(project_root).resolve(strict=True); node=Path(node_executable).resolve(strict=True); runtime=check_runtime(project); entry_sha=sha(SKILL/ENTRY); node_sha=sha(node)
 def guarded_loader(job,recipe,component):
  from edit.hd.tools import visual_canary
  if sha(SKILL/ENTRY)!=entry_sha or sha(node)!=node_sha or check_runtime(project)!=runtime: raise ValueError("Wise implementation or runtime changed")
  payload=brief_loader(job,recipe,component)
  b=validate_brief(payload); plan=visual_canary.load_approved_visual_plan(job); seg=next(x for x in plan["segments"] if x["segment_id"]==recipe["segment_id"]); ar=visual_canary.approved_aroll_record(job,plan)
  if json.loads(json.dumps(recipe))!=seg["shot_recipe"] or b["template_request"]!=json.loads(json.dumps(component["invocation_record"]["template_request"])) or b["source_binding"]!={"aroll_sha256":ar["sha256"],"segment_id":seg["segment_id"],"start":seg["start"],"end":seg["end"]}: raise ValueError("Wise source binding changed")
  if component.get("template_origin")!="custom_fallback" or component.get("adaptation_level")!="structural" or component.get("artifact_contract")!={"width":1080,"height":1920,"fps":24,"alpha":False} or component.get("source_sha256")!=entry_sha or component["render_window"].get("start_frame")!=0 or component["render_window"].get("end_frame")!=b["composition"]["frames"]: raise ValueError("Wise component contract changed")
  return payload
 return ReferenceProcessAdapter(adapter_id="wise-motion-native-orbit-v3",dependency_id=DEPENDENCY_ID,approved_executor="reference_adapter",dependency_root=SKILL,entrypoint=ENTRY,entrypoint_sha256=entry_sha,producer_version=VERSION,primary_renderer="Remotion",renderer_version="4.0.532",artifact_media_type="video",launcher=node,launcher_sha256=node_sha,brief_loader=guarded_loader,media_loader=None,self_contained_wrapper=True,timeout_seconds=300,argv_template=("{launcher}","{entrypoint}","--brief","{brief_path}","--runtime",runtime["path"],"--browser",runtime["browser"],"--skill-root",str(SKILL),"--output","{output_path}"))
def create_binding(adapter,brief_bytes,reference_sample):
 b=validate_brief(brief_bytes); e=sha(SKILL/ENTRY); digest=hashlib.sha256(brief_bytes).hexdigest()
 if adapter.dependency_id!=DEPENDENCY_ID or adapter.entrypoint_sha256!=e: raise ValueError("Wise adapter identity changed")
 return {"producer_type":"dependency","dependency_id":DEPENDENCY_ID,"entrypoint":ENTRY,"producer_version":VERSION,"primary_renderer":"Remotion","renderer_version":"4.0.532","template_origin":"custom_fallback","template_id":"wise-motion/orbit-tracking-component","template_version":VERSION,"adaptation_level":"structural","source_entrypoint":ENTRY,"source_sha256":e,"sample_sha256":sha(reference_sample),"semantic_families":["continuous_tracking"],"capacity":{"min_units":3,"max_units":3},"brief_sha256":digest,"verification_id":hashlib.sha256((e+digest).encode()).hexdigest(),"invocation_record":{"argv":[str(adapter.launcher),ENTRY],"status":"planned","exit_code":None,"template_request":b["template_request"]}}
def create_artifact_probe(ffprobe_executable):
 from whiteboard_adapter import create_artifact_probe
 return create_artifact_probe(ffprobe_executable)
if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--project-root",required=True); args=p.parse_args(); check_runtime(args.project_root)
 print(json.dumps({"schema_version":1,"dependency_id":DEPENDENCY_ID,"entrypoint":ENTRY,"producer_version":VERSION,"adapter_identity":{"adapter_type":"ReferenceProcessAdapter","approved_executor":"reference_adapter","primary_renderer":"Remotion"}}))

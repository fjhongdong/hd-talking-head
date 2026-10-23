"""All catalog routes with source-native scenes and explicit synthetic media.
Never a new-narration or artistic acceptance fixture.
"""
import json,re,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
from build_macro_project import scene_parts
from portrait_fixture import PLACEHOLDER

def create(directory):
 directory=Path(directory);directory.mkdir(exist_ok=True)
 catalog=json.loads((ROOT/'references/template-catalog.json').read_text());rows=[]
 packs={}
 for p in (ROOT/'packs').glob('*/*/manifest.json'):
  m=json.loads(p.read_text());packs[m['id']+'@'+m['version']]=(p.parent,m)
 for name in ['anim3','anim4']:
  p=ROOT/'packs'/name;m=json.loads((p/'manifest.json').read_text());packs[name+'@legacy']=(p,m)
 catalog.get('templates',catalog.get('categories',[])).append({'styles':[dict(id=name,selection=name+'@legacy',layouts={'landscape':{}}) for name in ['anim3','anim4']]})
 for group in catalog.get('templates',catalog.get('categories',[])):
  for style in group['styles']:
   for layout,contract in style['layouts'].items():
    selection=contract.get('selection',style['selection']);pack,m=packs[selection]
    out=directory/(style['id']+'-'+layout);out.mkdir();(out/'assets').mkdir()
    (out/'assets/demo-presenter.svg').write_text(PLACEHOLDER)
    for name in ['demo-media.js','noise.svg','presenter.svg','evidence.svg']:
     shutil.copy2(ROOT/'examples/portrait-catalog'/name,out/name)
    # The preview helper maps every episode image request to named QA SVGs.
    helper=(out/'demo-media.js').read_text().replace("new URL('../',location.href)","new URL('./',location.href)")
    (out/'demo-media.js').write_text(helper)
    if m.get('sourceFormat')=='authored-unit/1':
     pre='';blocks=[(pack/sc['sourceCodeFile']).read_text() for sc in m['scenes']];lib=(pack/'lib.js').read_text()
    else:
     pre,blocks=scene_parts((pack/'scenes.js').read_text());lib=(ROOT/'template/lib.js').read_text()
     pre=re.sub(r'function faceAt\(t\) \{[\s\S]*?\n\}(?=\nfunction camAt)','',pre,count=1).replace('RACE_K','PACK_RACE_K')
    (out/'lib.js').write_text(lib)
    (out/'scenes.js').write_text('window.MACRO_SOURCE_SFX=[];\n'+pre+'\n'+''.join('{const before=SFX.length;'+b+';window.MACRO_SOURCE_SFX.push(SFX.slice(before));}\n' for b in blocks))
    css=re.sub(r'@font-face\s*\{[^}]*\}', '', (pack/'style.css').read_text(),flags=re.I)
    css=re.sub(r'url\([^)]*\.(?:png|jpg|webp)[^)]*\)', 'url(noise.svg)', css,flags=re.I)
    (out/'style.css').write_text(css)
    runtime=''
    for name in m.get('runtimeFiles',[]):
     if 'font' not in name:
      shutil.copy2(pack/name,out/name);runtime+='<script src="'+name+'"></script>'
    variant=m.get('layouts',{}).get(layout,{})
    for key in ['runtime','stylesheet']:
     if variant.get(key):shutil.copy2(pack/variant[key],out/variant[key])
    w,h=(1080,1920) if layout=='portrait' else (1920,1080)
    plan=[];frame=0
    for i,sc in enumerate(m['scenes']):
     n=round((sc['source']['end']-sc['source']['start'])*60)
     plan.append({'id':str(i),'sceneId':sc['id'],'output_start_frame':frame,'output_end_frame':frame+n,'time_map':[{'output_frame':frame,'source':sc['source']['start']},{'output_frame':frame+n,'source':sc['source']['end']}]});frame+=n
    config=dict(demo=True,fps=60,width=w,height=h,end=frame/60,subtitles=False,talkFrames=0,brand='LAYOUT QA',race={'keys':[0,frame/60,frame/60+1],'labels':['test','end']})
    boot='window.CONFIG='+json.dumps(config)+';window.PACK_LAYOUT='+json.dumps(dict(name=layout,width=w,height=h,pack=m['id']))+';window.SHOWCASE_LAYOUT={...PACK_LAYOUT,layout:PACK_LAYOUT.name};window.PACK_BRAND_HTML="LAYOUT QA";window.PACK_PRESENTER_LABEL="NO PERSON";window.DOUBAO_OUTPUT_VOX=Array(20000).fill(0);window.PACK_NUMBERS={};window.MACRO_IS_OPENING_SCENE=true;window.MACRO_OUTPUT_T=0;const WALL=Array.from({length:389},(_,i)=>["QA"+i,""]);const FACE={};const SUBS=[];window.MACRO_PLAN='+json.dumps(dict(fps=60,end_frame=frame,scenes=plan))+';'
    shutil.copy2(ROOT/'scripts/macro_runtime.js',out/'macro_main.js')
    tags=lambda key:'<'+('link rel="stylesheet" href="'+variant[key]+'">' if key=='stylesheet' else 'script src="'+variant[key]+'"></script>') if variant.get(key) else ''
    entry='<meta charset="utf-8"><script src="demo-media.js"></script><link rel="stylesheet" href="style.css">'+tags('stylesheet')+'<div id="stage"><div id="world"></div><div id="fx"></div><div id="ov"></div></div><script>'+boot+'</script><script src="lib.js"></script>'+runtime+'<script src="scenes.js"></script><script src="macro_main.js"></script>'+tags('runtime')
    (out/'index.html').write_text(entry);(out/'plan.json').write_text(json.dumps(plan));(out/'macro_plan.json').write_text(json.dumps(dict(width=w,height=h,scenes=plan)))
    rows.append(dict(id=style['id'],layout=layout,selection=selection,width=w,height=h,duration=frame/60,groups=len(plan),directory=out.name))
 # All nine starter components use the same normal renderAt(t) runtime.
 out=directory/'TPL-9';shutil.copytree(ROOT/'template',out)
 for name in ['talkmap.js','face.js','subs.js','wall.js']:(out/name).write_text('// Optional QA data absent.\n')
 for name in ['demo-media.js','noise.svg','presenter.svg','evidence.svg']:shutil.copy2(ROOT/'examples/portrait-catalog'/name,out/name)
 helper=(out/'demo-media.js').read_text().replace("new URL('../',location.href)","new URL('./',location.href)");(out/'demo-media.js').write_text(helper)
 p=out/'index.html';p.write_text(p.read_text().replace('<head>','<head><script src="demo-media.js"></script>',1))
 p=out/'style.css';p.write_text(re.sub(r'@font-face\s*\{[^}]*\}', '', p.read_text(),flags=re.I))
 boundaries=[0,4,8,12,16,20,23,27,31,36]
 (out/'plan.json').write_text(json.dumps([dict(output_start_frame=a*60,output_end_frame=b*60) for a,b in zip(boundaries,boundaries[1:])]))
 rows.append(dict(id='TPL-9',layout='landscape',selection='base-components',width=1920,height=1080,duration=36,groups=9,directory='TPL-9'))
 (directory/'routes.json').write_text(json.dumps(rows,indent=2));return rows
if __name__=='__main__':create(sys.argv[1])

// Static composition bridge; all animation is the unmodified Wise component.
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const a=process.argv.slice(2), names=['--brief','--runtime','--browser','--skill-root','--output'];
if(a.length!==10||names.some((n,i)=>a[i*2]!==n)) throw new Error('Expected brief, runtime, browser, skill root and output paths');
const o=Object.fromEntries(names.map((n,i)=>[n,a[i*2+1]]));
if(!Object.values(o).every(path.isAbsolute)) throw new Error('Use absolute paths');
const brief=JSON.parse(await readFile(o['--brief'],'utf8')); const require=createRequire(path.join(o['--runtime'],'package.json'));
const wise=await import(require.resolve('wise-motion')); const {resolveEffect,validateContent,getEffectMetadata}=wise;
if(JSON.parse(await readFile(path.join(o['--runtime'],'node_modules/wise-motion/package.json'),'utf8')).version!=='0.1.21') throw new Error('Wise package changed');
const {bundle}=require('@remotion/bundler');
const {renderMedia,selectComposition}=require('@remotion/renderer');
if(brief.template_request?.semantic_family!=='continuous_tracking'||brief.context_labels?.length!==3||brief.layers?.length!==1) throw new Error('Invalid native tracking brief');
for(const layer of brief.layers??[]){
 if(layer.id!=='orbit'||layer.transparent!==false||layer.from!==0) throw new Error('Unsupported Wise layer');
 const def=resolveEffect(layer.id); validateContent(def,layer.content);
 const meta=getEffectMetadata(def,{fps:24,speed:layer.speed,variantId:'original'});
 if(meta.durationMs!==6000||meta.loop!==true) throw new Error('Native continuous motion changed');
}
const frames=brief.composition.frames;
if(!Number.isInteger(frames)||frames<=0) throw new Error('Invalid voice window');
console.log(JSON.stringify({status:'validated',package_version:'0.1.21',template_id:'wise-motion/orbit-tracking-component',frames,layers:brief.layers.length,external_requests:0}));
const temporary=await mkdtemp(path.join(o['--runtime'],'.render-'));
try {
 const serveUrl=await bundle({entryPoint:path.join(o['--skill-root'],'assets/wise-motion-runtime/index.jsx'),publicDir:path.join(o['--runtime'],'public'),outDir:path.join(temporary,'bundle'),webpackOverride:config=>({...config,resolve:{...config.resolve,modules:[path.join(o['--runtime'],'node_modules'),...(config.resolve?.modules??[])]}})});
 const options={serveUrl,browserExecutable:o['--browser'],inputProps:brief};
 const composition=await selectComposition({...options,id:'WiseNative'});
 if(composition.width!==1080||composition.height!==1920||composition.fps!==24||composition.durationInFrames!==frames) throw new Error('Native composition clock changed');
 // The executor owns a suffixless staging path; Remotion needs an .mp4 name.
 const nativeOutput=path.join(temporary,'native.mp4');
 await renderMedia({...options,composition,outputLocation:nativeOutput,codec:'h264',pixelFormat:'yuv420p',
  colorSpace:'bt709',muted:true,concurrency:1,
  ffmpegOverride:({type,args})=>type==='stitcher'?[...args.slice(0,-1),'-bsf:v','h264_metadata=sample_aspect_ratio=1/1',args.at(-1)]:args});
 await writeFile(o['--output'],await readFile(nativeOutput));
 console.log(JSON.stringify({status:'rendered',package_version:'0.1.21',frames,external_requests:0}));
} finally { await rm(temporary,{recursive:true}); }

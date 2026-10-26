'use strict';
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module'),{pathToFileURL}=require('node:url');
async function main(){
 const [project,entry,id,secondsText]=process.argv.slice(2),seconds=Number(secondsText);
 if(!project||!entry||!id||!Number.isFinite(seconds)||seconds<=0)throw Error('invalid native clock input');
 const req=createRequire(path.join(project,'skill-development/runtime/hyperframes-0.8.167/package.json'));
 const puppeteer=req('puppeteer-core'),errors=[];
 const browser=await puppeteer.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--no-sandbox','--disable-gpu']});
 try{
  const page=await browser.newPage();await page.setViewport({width:1080,height:1920,deviceScaleFactor:1});
  await page.setRequestInterception(true);page.on('request',r=>{if(/^(file:|data:|about:)/.test(r.url()))r.continue();else {errors.push('external resource: '+r.url().split('?')[0]);r.abort();}});
  page.on('pageerror',e=>errors.push(e.message));await page.goto(pathToFileURL(entry).href,{waitUntil:'load',timeout:15000});
  const result=await page.evaluate(({id,seconds})=>{
   const tl=window.__timelines&&window.__timelines[id];if(!tl||typeof tl.seek!=='function'||typeof tl.duration!=='function'||typeof tl.pause!=='function')throw Error('native paused timeline is missing');
   if(typeof tl.paused!=='function'||!tl.paused())throw Error('native timeline must already be paused');
   if(Math.abs(tl.duration()-seconds)>1/24)throw Error('native timeline duration differs from approved frames');
   const labels=[...document.querySelectorAll('[data-copy-primary]')];if(labels.length!==1)throw Error('callout needs exactly one primary label');
   const label=labels[0],measure=t=>{tl.seek(t,false);const r=label.getBoundingClientRect();let opacity=1,e=label;for(;e&&e.nodeType===1;e=e.parentElement){let s=getComputedStyle(e);if(s.visibility==='hidden'||s.display==='none')opacity=0;opacity*=Number(s.opacity);}return {time:t,opacity,text:label.textContent.trim(),bbox:[r.x,r.y,r.width,r.height]};};
   const frames=Math.round(seconds*24),samples=[];
   for(let f=0;f<frames;f++)samples.push(measure(f/24));
   const on=samples.find(s=>s.opacity>.01),stable=samples.filter(s=>s.opacity>=.95),last=samples[samples.length-1];
   if(!on||!stable.length)throw Error('native label never becomes readable');
   if(last.opacity>.01)throw Error('native label does not exit before final frame');
   const a=measure(seconds/2),b=measure(0),c=measure(seconds-1/24),d=measure(seconds/2);
   if(JSON.stringify(a)!==JSON.stringify(d))throw Error('native frame depends on seek history');
   return {id,duration:tl.duration(),label:on.text,reveal_time:on.time,first_readable_time:stable[0].time,last_readable_time:stable.at(-1).time,bbox:stable[Math.floor(stable.length/2)].bbox,prior_hidden:!samples.some(s=>s.time<on.time&&s.opacity>.01),last_opacity:last.opacity};
  },{id,seconds});
  if(errors.length)throw Error(errors.join('; '));process.stdout.write(JSON.stringify(result));
 }finally{await browser.close();}
}
main().catch(e=>{process.stderr.write(e.message+'\n');process.exitCode=1;});

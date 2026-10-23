// Real catalog scene code, synthetic local imagery: decorative regression only.
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';import {spawnSync} from 'node:child_process';
import {chromium} from 'playwright-core';import {chrome} from '../scripts/chrome.mjs';
import {createSignature} from '../scripts/output-signature.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'adu-signature-test-'));
const keep=process.env.ADU_SIGNATURE_REPORT;let browser;const results=[];
try{
 const made=spawnSync(process.env.ADU_TEST_PYTHON||'python3',[root+'/tests/signature_fixture.py',temporary],{encoding:'utf8'});assert.equal(made.status,0,made.stderr);
 const rows=JSON.parse(fs.readFileSync(temporary+'/routes.json'));
 browser=await chromium.launch({executablePath:chrome(),headless:true,args:['--allow-file-access-from-files','--disable-gpu','--disable-accelerated-2d-canvas','--force-color-profile=srgb']});
 for(const row of rows){
  const page=await browser.newPage({viewport:{width:row.width,height:row.height}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>/\.(jpg|jpeg|png|svg|webp)(\?|$)/.test(r.request().url())?r.fulfill({body:fs.readFileSync(temporary+'/'+row.directory+'/presenter.svg'),contentType:'image/svg+xml'}):r.continue());
  await page.goto(pathToFileURL(temporary+'/'+row.directory+'/index.html').href);await page.evaluate(()=>window.READY);
  const sound=await page.evaluate(()=>JSON.stringify(SFX)),plan=JSON.parse(fs.readFileSync(temporary+'/'+row.directory+'/plan.json'));
  const sig=await createSignature(page,{width:row.width,height:row.height,duration:row.duration,fps:60,mode:'dom',selector:'#stage'});
  async function frame(t){await sig.before();await page.evaluate(async t=>{await renderAt(t);await imgWait();},t);await sig.draw(t);return page.evaluate(()=>MOTIONGIT_SIGNATURE_STATE);}
  // Every active scene, output-clock positions, source SFX, reversible seeks.
  for(const item of plan){
   const t=(item.output_start_frame+Math.floor((item.output_end_frame-item.output_start_frame)*.5))/60;
   const state=await frame(t);assert.equal(state.time,Math.floor(t*60+1e-6)/60);
   assert.ok(state.centerX+state.diameter/2<row.width-30 && state.centerY-state.diameter/2>=40);
   assert.equal(await page.locator('[data-motiongit-signature]').count(),1);
   assert.equal(await page.evaluate(()=>[...document.querySelectorAll('.tc span')].some(n=>/^\d{2}:\d{2}:\d{2}:\d{2}$/.test(n.textContent)&&n.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))),false,'decorative source HUD clock duplicated');
  }
  const first=await frame(1),mark=await frame(9),again=await frame(1);
  assert.deepEqual(first,again,row.directory+' backward seek');assert.equal(first.clock,'00:01');assert.equal(mark.envelope,1);assert.equal(mark.clockOpacity,0);
  const crop={x:row.width-270,y:0,width:270,height:220};
  const a=await page.screenshot({clip:crop});await frame(10);const b=await page.screenshot({clip:crop});
  assert.notDeepEqual(a,b,row.directory+' animated signature actually changes');
  assert.equal(await page.evaluate(()=>JSON.stringify(SFX)),sound);assert.deepEqual(errors,[],row.directory);
  if(keep){fs.mkdirSync(path.dirname(keep),{recursive:true});await page.screenshot({path:path.join(path.dirname(keep),row.directory+'.png')});}
  results.push({...row,passed:true,groupsChecked:plan.length});await page.close();
 }
 // Same-origin mixed composition: retain one parent layer and user branding.
 const page=await browser.newPage({viewport:{width:1920,height:1080}});
 await page.setContent('<style>body{margin:0}#stage{position:relative;width:1920px;height:1080px}iframe{width:1920px;height:1080px;border:0}</style><div id="stage"><iframe srcdoc="<style>body{margin:0}#stage{width:1920px;height:1080px} .e{position:absolute;right:64px;top:52px}</style><div id=stage><div class=e><b>MY BRAND</b> <span>00:02:04:11</span></div><div style=position:absolute;left:100px;top:500px class=time>12:30</div></div>"></iframe></div>');
 const sig=await createSignature(page,{width:1920,height:1080,duration:36,fps:60,mode:'dom',selector:'#stage'});
 await sig.before();await sig.draw(11);
 assert.equal(await page.locator('[data-motiongit-signature]').count(),1);
 const child=page.frames()[1];assert.equal(await child.locator('[data-motiongit-source-clock]').count(),1);
 assert.equal(await child.locator('b').isVisible(),true);assert.equal(await child.locator('.time').isVisible(),true);
 const brand=await child.locator('b').boundingBox();assert.ok(brand.x+brand.width<1696,'brand clears signature slot');
 // Tone follows the actual painted background, including seeks back to white.
 for(const [bg,tone] of [['white','path'],['black','lighter'],['white','path']]){
  await page.evaluate(bg=>{document.querySelector('iframe').style.display='none';document.querySelector('#stage').style.background=bg;},bg);await sig.before();await sig.draw(10);
  assert.equal(await page.evaluate(()=>MOTIONGIT_SIGNATURE_STATE.tone),tone);
 }
 await page.close();
 const report={passed:true,catalogStyles:11,totalRoutes:rows.length,groups:results.reduce((n,r)=>n+r.groupsChecked,0),checks:['native current catalog scenes','safe corner','one output layer','output time','animated frames','reverse seek','source SFX unchanged','local mixed iframe clock/brand handling','light/dark tone'],routes:results,scope:'Synthetic imagery and system fonts; not human narration AV or Windows hardware acceptance'};
 if(keep)fs.writeFileSync(keep,JSON.stringify(report,null,2));console.log(JSON.stringify({...report,routes:results.length}));
}finally{if(browser)await browser.close();fs.rmSync(temporary,{recursive:true,force:true});}

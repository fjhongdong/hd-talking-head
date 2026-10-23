"""Opt-in real browser measurements; one Chromium instance, no external calls."""

import json
import os
import subprocess
import unittest
import sys
import tempfile
import select
from pathlib import Path

from edit.hd.tests.test_semantic_state_renderer import brief, RENDERER


def run_browser_check(script, arguments, payload, *, timeout=90, browser_executable=None):
    """Keep browser ownership outside Node, including after a Node timeout."""
    tools = RENDERER.parent
    with tempfile.TemporaryDirectory() as directory:
        read_fd, write_fd = os.pipe()
        try:
            watchdog = subprocess.Popen(
                [sys.executable, str(tools / "relation_browser_watchdog.py"),
                 "--heartbeat-fd", str(read_fd), "--parent", str(Path(directory).resolve())],
                pass_fds=(read_fd,), start_new_session=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except BaseException:
            os.close(write_fd)
            raise
        finally:
            os.close(read_fd)
        try:
            if not select.select([watchdog.stdout], [], [], 5)[0]:
                raise RuntimeError("browser watchdog readiness timeout")
            ready = json.loads(watchdog.stdout.readline())
            environment = dict(os.environ,
                               HD_BROWSER_SOCKET=ready["socket"],
                               HD_BROWSER_TOKEN=ready["token"],
                               HD_BROWSER_REAL=browser_executable or os.environ["HD_CHROMIUM"],
                               HD_CHROMIUM=str(tools / "relation_browser_shim.py"))
            return subprocess.run(["node", "-e", script, *arguments], input=payload,
                                  text=True, capture_output=True, timeout=timeout,
                                  env=environment)
        finally:
            os.close(write_fd)
            # Do not kill the watchdog before its registered-group cleanup finishes.
            try:
                _, errors = watchdog.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                watchdog.kill()
                watchdog.communicate(timeout=5)
                raise RuntimeError("browser watchdog cleanup deadline exceeded")
            if watchdog.returncode:
                raise RuntimeError("browser watchdog cleanup failed: " + errors[-2000:])


BROWSER_CHECK = r"""
const fs=require('node:fs'),http=require('node:http'),crypto=require('node:crypto');
const renderer=require(process.argv[1]);
const {chromium}=require(process.env.HD_PLAYWRIGHT);
const cases=JSON.parse(fs.readFileSync(0,'utf8')).map(renderer.validateBrief);
const server=http.createServer((req,res)=>{
  const match=/^\/(\d+)\/(\d+)$/.exec(req.url);
  if(!match){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
  res.end(renderer.htmlFor(cases[Number(match[1])]));
});
let browser;
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({executablePath:process.env.HD_CHROMIUM,headless:true});
  const context=await browser.newContext({viewport:{width:1080,height:1920},deviceScaleFactor:1});
  const external=[],errors=[];
  await context.route('**/*',route=>{
    if(new URL(route.request().url()).origin===origin)return route.continue();
    external.push(route.request().url());return route.abort();
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  const reports=[];
  for(let i=0;i<cases.length;i++){
    const hashes={},violations=[],layoutViolations=[];
    for(const frame of [0,20,30,40,50,60,72,107,108,114,119]){
      await page.goto(`${origin}/${i}/${frame}`,{waitUntil:'load'});
      const actual=await page.evaluate(frame=>window.seekFrame(frame),frame);
      if(await page.evaluate(()=>globalThis.injected===1))throw new Error('inline data executed');
      if(JSON.stringify(actual)!==JSON.stringify(renderer.frameState(cases[i],frame)))
        throw new Error('browser/core frame state mismatch');
      await page.evaluate(()=>document.fonts.ready);
      const measured=await page.evaluate(()=>{
        const bad=[];
        for(const group of document.querySelectorAll('[data-subject]')){
          if(Number(getComputedStyle(group).opacity)===0)continue;
          const box=group.querySelectorAll('rect')[1].getBBox();
          for(const text of group.querySelectorAll('text')){
            if(Number(getComputedStyle(text).opacity)===0)continue;
            const b=text.getBBox();
            if(b.x<box.x+15||b.x+b.width>box.x+box.width-15||b.y<box.y+10||b.y+b.height>box.y+box.height-10)
              bad.push({subject:group.dataset.subject,text:text.textContent,box:{x:box.x,y:box.y,width:box.width,height:box.height},bounds:{x:b.x,y:b.y,width:b.width,height:b.height}});
          }
        }
        return bad;
      });
      violations.push(...measured.map(v=>({frame,...v})));
      const layout=await page.evaluate(()=>{
        const box=element=>{const b=element.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
        const visible=[...document.querySelectorAll('[data-role]')]
          .filter(element=>Number(getComputedStyle(element).opacity)>0)
          .map(element=>({role:element.dataset.role,bounds:box(element)}));
        const bad=[];
        for(const item of visible){
          const b=item.bounds;
          if(b.x<0||b.y<0||b.right>1080||b.bottom>1920)bad.push({reason:'canvas-overflow',...item});
          if(item.role==='content-unit'&&b.y<350)bad.push({reason:'title-collision',...item});
          if(!['header','payoff'].includes(item.role)&&b.right>796&&b.x<1020&&b.bottom>1450&&b.y<1674)
            bad.push({reason:'avatar-collision',...item});
        }
        for(const text of document.querySelectorAll('[data-text-size]')){
          if(Number(text.dataset.textSize)<18)bad.push({reason:'unreadable-text',role:text.closest('[data-role]')?.dataset.role||'text',bounds:box(text)});
        }
        const payoffElement=document.querySelector('[data-role="payoff"]');
        const payoffBounds=payoffElement?box(payoffElement):null;
        if(!payoffBounds||payoffBounds.bottom>1600)bad.push({reason:'payoff-safe-zone',role:'payoff',bounds:payoffBounds});
        return bad;
      });
      layoutViolations.push(...layout.map(v=>({frame,...v})));
      if([0,30,50,72,119].includes(frame)){
        const png=await page.screenshot();hashes[frame]=crypto.createHash('sha256').update(png).digest('hex');
        if(frame===72&&process.env.HD_SEMANTIC_SCREENSHOTS)
          await page.screenshot({path:require('node:path').join(process.env.HD_SEMANTIC_SCREENSHOTS,`case-${i}-${cases[i].motion.family}.png`)});
      }
    }
    reports.push({family:cases[i].motion.family,violations,layoutViolations,hashes});
  }
  process.stdout.write(JSON.stringify({reports,external,errors}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
});
"""


def capacity_cases():
    result = []
    for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
        value = brief(family, layer_count=4)
        value["title"] = "一二三四五六七八九十一二"
        for s in value["motion"]["subjects"]:
            s["label"] = "一二三四五六七八" if family == "threshold" else "一二三四五六七八九十一二"
            s["initial_state"] = "初始状态一二三四五六七八九十一二"
            s["final_state"] = s["initial_state"] if s["preserve"] else "最终状态一二三四五六七八九十一二"
        result.append(value)
    many = json.loads(json.dumps(result[0]))
    many["motion"]["source_text"] = '</script><script>globalThis.injected=1</script>'
    for suffix in (2, 3):
        subject_id = f"workflow{suffix}"
        many["motion"]["subjects"].append({**many["motion"]["subjects"][1], "id": subject_id})
        many["roles"]["context_ids"].append(subject_id)
        for i in (0, 2):
            many["motion"]["actions"][i]["subject_ids"].append(subject_id)
    result.append(many)
    return result


@unittest.skipUnless(os.environ.get("HD_PLAYWRIGHT") and os.environ.get("HD_CHROMIUM"),
                     "set explicit local Playwright/Chromium paths for real-browser QA")
class SemanticStateBrowserTests(unittest.TestCase):
    def test_real_chinese_text_capacity_motion_and_reading_pixels(self):
        result = run_browser_check(BROWSER_CHECK, [str(RENDERER)], json.dumps(capacity_cases()))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["external"], [])
        for case in report["reports"]:
            with self.subTest(family=case["family"]):
                self.assertEqual(case["violations"], [])
                self.assertEqual(case["layoutViolations"], [])
                self.assertEqual(case["hashes"]["72"], case["hashes"]["119"])
                self.assertNotEqual(case["hashes"]["0"], case["hashes"]["30"])
                self.assertNotEqual(case["hashes"]["30"], case["hashes"]["50"])
                self.assertNotEqual(case["hashes"]["50"], case["hashes"]["72"])


class BrowserLifecycleTests(unittest.TestCase):
    def test_timeout_reclaims_registered_detached_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "child.pid"
            script = """
const {spawn}=require('node:child_process');
spawn(process.env.HD_CHROMIUM,['-c',
 'import os,time; from pathlib import Path; Path('+JSON.stringify(process.argv[1])+').write_text(str(os.getpid())); time.sleep(30)'],
 {detached:true,stdio:'ignore'}).unref();
setInterval(()=>{},1000);
"""
            runner = globals().get("run_browser_check")
            self.assertIsNotNone(runner, "browser QA needs supervised lifecycle")
            with self.assertRaises(subprocess.TimeoutExpired):
                runner(script, [str(pid_file)], "", timeout=3,
                       browser_executable=sys.executable)
            self.assertTrue(pid_file.exists(), "detached child must start before timeout")
            from edit.hd.tools.relation_browser_watchdog import _group_has_live_members
            self.assertFalse(_group_has_live_members(int(pid_file.read_text())))


if __name__ == "__main__":
    unittest.main()

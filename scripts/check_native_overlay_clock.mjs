#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {createServer} from "node:http";

const fail = (message) => { throw new Error(message); };

const input = JSON.parse(await new Promise((resolve, reject) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { data += chunk; });
  process.stdin.on("end", () => resolve(data));
  process.stdin.on("error", reject);
}));
if (!input || typeof input.project_root !== "string" || !Array.isArray(input.entries)) fail("invalid checker input");

const project = path.resolve(input.project_root);
const runtimeRoot = path.join(project, "skill-development/runtime/hyperframes-0.8.167");
const compiler = await import(path.join(runtimeRoot, "node_modules/hyperframes/dist/chunk-AATVO56S.js"));
const {seekCompositionTimeline,waitForRuntimeReady} = await import(path.join(runtimeRoot, "node_modules/hyperframes/dist/chunk-JK2AETXO.js"));
const puppeteer = await import(path.join(runtimeRoot, "node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js"));
const chrome = path.join(project, ".remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell");
const gsapBody = await fs.readFile(path.join(project, "参考项目/B-roll开源方案/hyperframes/skills/talking-head-recut/assets/vendor/gsap.min.js"), "utf8");

const results = [];
let html = "";
const server = createServer((req, res) => {
  const script = req.url === "/vendor/gsap.min.js";
  res.writeHead(200, {"Content-Type": script ? "application/javascript" : "text/html; charset=utf-8"});
  res.end(script ? gsapBody : html);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await puppeteer.launch({ executablePath: chrome, headless: "shell", args: ["--no-sandbox"] });
try {
for (const item of input.entries) {
  const directory = path.resolve(project, item.entry_directory);
  html = await compiler.bundleToSingleHtml(directory, {entryFile: "index.html"});
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => {if (message.type() === "error") errors.push(message.text());});
    await page.setRequestInterception(true);
    page.on("request", (request) => {
      const url = request.url();
      if (/^https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@[^/]+\/dist\/gsap\.min\.js$/.test(url)) request.respond({ status: 200, contentType: "application/javascript", body: gsapBody });
      else if (url.startsWith(origin + "/") || url.startsWith("data:")) request.continue(); else request.abort();
    });
    await page.goto(origin + "/index.html", {waitUntil:"load"});
    await page.waitForFunction(name => !!window.__timelines?.[name], {timeout:10000}, item.route.slice("hyperframes/".length));
    if (!await waitForRuntimeReady(page,10000)) fail('bundled runtime did not become ready');
    const observed = await page.evaluate(({ route, duration, start, events }) => {
      const name = route.slice("hyperframes/".length);
      const hostNodes = [...document.querySelectorAll(`[data-composition-id="${name}"]`)];
      if (hostNodes.length !== 1) throw new Error("expected one host composition node");
      const host = hostNodes[0];
      const inner = document.querySelector('[data-hf-authored-id="root"]');
      if (!inner || inner.hasAttribute("data-duration")) throw new Error("inner root duration was not stripped");
      const clip = document.getElementById(`${name}-clip`);
      if (!clip || Number(clip.getAttribute("data-start")) !== 0) throw new Error("native clip is not zero-based");
      if (Number(host.getAttribute("data-start") || 0) !== Number(start)) throw new Error("host start mismatch");
      const tl = window.__timelines?.[name];
      if (!tl || typeof tl.getChildren !== "function") throw new Error("native timeline missing");
      if (inner.closest('[data-composition-id]') !== host || Math.abs(Number(host.dataset.duration)-duration)>1e-6 || Math.abs(Number(clip.dataset.duration)-duration)>1e-6)
        throw Error("native root or clip timing ownership differs");
      const children = tl.getChildren(false, true, false), near = (a,b) => Math.abs(a-b)<1e-6;
      const actual = [];
      for (const event of events) {
        const local = event.time-start;
        if (name === "toggle-flip" && event.kind === "reveal") {
          if (!near(local,0)) throw Error("toggle label must begin at mount start");
          actual.push({kind:event.kind,slot:event.slot,local_time:0});
          continue;
        }
        const node = name === "toggle-flip" ? host.querySelector('.tf-knob')
          : host.querySelectorAll(name === "grid-card-assemble" ? '.gca-card' : '.ns-card')[event.slot];
        const tweens = children.filter(t => t.targets().includes(node) && (name === "toggle-flip" ? t.vars.x !== undefined : t.vars.opacity === 1));
        if (!node || tweens.length !== 1 || !near(tweens[0].startTime(),local))
          throw Error(`native event differs: ${event.kind}/${event.slot}`);
        actual.push({kind:event.kind,slot:event.slot,local_time:tweens[0].startTime()});
      }
      const values = JSON.parse(host.dataset.variableValues || '{}');
      const out = name === 'toggle-flip' ? .5*Math.min(1,duration/1.4) : !values.exit || values.exit === 'none' ? 0 : Math.min(.45,duration*.25);
      let exitStart = null;
      if (out>0) {
        const stage = host.querySelector(name === 'toggle-flip' ? '.tf-stage' : name === 'grid-card-assemble' ? '.gca-stage' : '.ns-stage');
        const exits = children.filter(t => t.targets().includes(stage) && t.vars.opacity === 0);
        if (exits.length !== 1 || !near(exits[0].startTime(),duration-out)) throw Error('native exit still uses default duration');
        exitStart = exits[0].startTime();
      }
      return {route,native_duration:Number(duration),host_start:Number(start),timeline_duration:tl.duration(),exit_start:exitStart,events:actual};
    }, item);
    if (item.start>0) {
      if (!await page.evaluate(() => typeof window.__player?.renderSeek === 'function' || typeof window.__hf?.seek === 'function')) fail('parent seek API unavailable');
      await seekCompositionTimeline(page,item.start+.6,{fallbackToBridgeAndTimelines:true,exactTime:true,waitForVideoFrames:false});
      const local = await page.evaluate(name => window.__timelines[name].time(), item.route.slice("hyperframes/".length));
      if (Math.abs(local-.6)>1e-6) fail("native local clock has a repeated host offset");
      observed.seek_local_time = local;
    }
    if (errors.length) fail(errors.join('\n'));
    results.push(observed);
    await page.close();
}
} finally { await browser.close(); server.close(); }
process.stdout.write(JSON.stringify({ ok: true, entries: results }) + "\n");

#!/usr/bin/env node
// Reconstructed assembled-native-clock checker for the HD talking-head skill.
//
// Reads {"project_root": ..., "entries": [{entry_directory, route, duration,
// start, events}]} on stdin. For every assembled entry it loads the host HTML
// in the actual pinned HyperFrames preview runtime in headless system Chrome,
// blocks all non-loopback network access, then seeks the authored gsap timeline
// frame by frame on the approved 24 fps clock and
// records the observed entry/exit times, timeline duration, peak visible
// texts, and whether the temporary data-duration attribute was removed by the
// post-handoff snippet. No media export, no online access, no source edits.
//
// Prints {"ok": true, "entries": [...]} for overlay_alignment._assembled_clocks.

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { spawn } from "node:child_process";
import os from "node:os";
import { createRequire } from "node:module";
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';

const GSAP_CANDIDATES = [
  "参考项目/B-roll开源方案/hyperframes/skills/talking-head-recut/assets/vendor/gsap.min.js",
  "参考项目/B-roll开源方案/hyperframes/skills/music-to-video/references/motion-primitives/assets/gsap.min.js",
];
const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const PLAYWRIGHT_CANDIDATES = ["skill-development/runtime/adu-native/node_modules/playwright-core"];
const HYPERFRAMES = "skill-development/runtime/hyperframes-0.8.167/node_modules/hyperframes/bin/hyperframes.mjs";
const FPS = 24;

function firstExisting(root, relatives, absolute = false) {
  for (const relative of relatives) {
    const candidate = absolute ? relative : path.join(root, relative);
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

async function readStdinJson() {
  const stream = readline.createInterface({ input: process.stdin });
  let text = "";
  for await (const line of stream) text += line;
  return JSON.parse(text);
}

export const SAMPLE = async (entry, fps) => {
  const route = entry.route.replace(/^hyperframes\//, '');
  const mount = document.querySelector(`[data-composition-id="${route}"][data-composition-src]`);
  if (!mount) throw new Error('requested composition mount is missing');
  const roots = mount.querySelectorAll('[data-hf-authored-id="root"][data-hf-inner-root]');
  if (roots.length !== 1) throw new Error('requested native instance has no unique authored root');
  const root = roots[0];
  const timeline = window.__timelines?.[route];
  const player = window.__player;
  if (!timeline?.time || !timeline.duration || !player?.renderSeek || !player.getTime) {
    throw new Error('actual native timeline/player is not ready');
  }
  const total = timeline.duration();
  const hostTotal = player.getDuration();
  const tolerance = 1 / fps;
  if (Math.abs(total - entry.duration) > tolerance || hostTotal < entry.start + total - tolerance) {
    throw new Error('native duration differs from the declared clock');
  }
  const intersect = (a, b) => ({left: Math.max(a.left, b.left), right: Math.min(a.right, b.right),
    top: Math.max(a.top, b.top), bottom: Math.min(a.bottom, b.bottom)});
  const visible = (element, bounds = element.getBoundingClientRect()) => {
    let box = intersect(bounds, {left: 0, top: 0, right: 1080, bottom: 1920});
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) <= .01) return false;
      const rect = node.getBoundingClientRect();
      if (style.overflowX !== 'visible') box = intersect(box, {...box, left: rect.left, right: rect.right});
      if (style.overflowY !== 'visible') box = intersect(box, {...box, top: rect.top, bottom: rect.bottom});
      if (style.clipPath !== 'none') {
        const match = /^inset\(([^()]+)\)$/.exec(style.clipPath);
        if (!match) throw new Error('unsupported native clip path: ' + style.clipPath);
        const parts = match[1].trim().split(/\s+/);
        if (parts.length < 1 || parts.length > 4) throw new Error('unsupported native inset: ' + style.clipPath);
        const [t, r = t, b = t, l = r] = parts;
        const px = (value, length) => {
          if (!/^-?(?:\d*\.)?\d+(?:px|%)?$/.test(value)) throw new Error('unsupported native inset value: ' + value);
          return parseFloat(value) * (value.endsWith('%') ? length / 100 : 1);
        };
        box = intersect(box, {left: rect.left + px(l, rect.width), right: rect.right - px(r, rect.width),
          top: rect.top + px(t, rect.height), bottom: rect.bottom - px(b, rect.height)});
      }
      if (box.right <= box.left || box.bottom <= box.top) return false;
    }
    return box.right > box.left && box.bottom > box.top;
  };
  const texts = container => {
    const items = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.textContent.trim() || node.parentElement.closest('script,style,template,noscript,title,desc,metadata')) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      items.push({element: node.parentElement, rect: range.getBoundingClientRect(), text: node.textContent.trim()});
    }
    return items;
  };
  const seek = async time => {
    await player.renderSeek(time, {exact: true});
    if (window.__hfWaitForSeekCompletion) await window.__hfWaitForSeekCompletion();
    const expected = Math.max(0, Math.min(total, time - entry.start));
    if (Math.abs(player.getTime() - time) > tolerance || Math.abs(timeline.time() - expected) > tolerance) {
      throw new Error('native/player clocks diverge at ' + time);
    }
  };
  let entryFrame = null, exitFrame = null, peak = 0;
  const frames = Math.ceil(hostTotal * fps);
  for (let frame = 0; frame <= frames; frame++) {
    const time = Math.min(frame / fps, hostTotal);
    await seek(time);
    const count = texts(root).filter(item => visible(item.element, item.rect)).length;
    if (count) {entryFrame ??= frame; exitFrame = frame; peak = Math.max(peak, count);}
  }
  if (!peak) throw new Error('native content is never visible');
  const visibilityChecks = [];
  if (route === 'before-after-wipe') {
    const land = entry.events.find(event => event.kind === 'wipe_land');
    if (!land) throw new Error('before/after stable event is missing');
    const time = land.time + 1 / fps;
    if (time < entry.start || time >= entry.start + total) throw new Error('before/after stable event is outside the native window');
    await seek(time);
    const after = root.querySelector('.baw-after');
    const slot = after?.querySelector('[data-slot="after"]');
    if (!slot) throw new Error('after content slot is missing');
    const labels = texts(after);
    const graphics = [...slot.querySelectorAll('svg,img,canvas,[data-hd-critical]')]
      .filter(node => !node.parentElement.closest('svg'));
    if (!labels.length && !graphics.length) throw new Error('after slot has no inspectable content');
    for (const item of labels) {
      if (!visible(item.element, item.rect)) throw new Error('after text is clipped or hidden: ' + item.text);
    }
    for (const graphic of graphics) {
      if (!visible(graphic)) throw new Error('after graphic is clipped or hidden');
    }
    visibilityChecks.push({time, text_count: labels.length, graphic_count: graphics.length});
  }
  await seek(0);
  const stage = document.querySelector('.stage');
  return {ok: true, route, clock_space: 'segment', timeline_duration: total,
    entry_time: entryFrame / fps, exit_time: exitFrame / fps, peak_visible_texts: peak,
    temporary_duration_removed: !root.hasAttribute('data-duration'),
    host_duration: stage?.getAttribute('data-duration'), host_start: mount.getAttribute('data-start'),
    authored_root_id: root.getAttribute('data-hf-authored-id'), visibility_checks: visibilityChecks};
};

export function validateHostStyles(source) {
  const host = new DOMParser().parseFromString(source, 'text/html');
  if (host.querySelector('[id="root"]')) return;
  const inspect = rules => {
    for (const rule of rules) {
      if (rule.selectorText && /#root(?![\w-])/.test(rule.selectorText.replace(/\[[^\]]*\]/g, ''))) {
        throw new Error('host CSS targets rewritten #root; use component classes or the authored-root attribute');
      }
      if (rule.cssRules) inspect(rule.cssRules);
    }
  };
  for (const style of host.querySelectorAll('style')) {
    const sheet = new CSSStyleSheet(); sheet.replaceSync(style.textContent); inspect(sheet.cssRules);
  }
}

export async function runCheck(request) {
  const projectRoot = request.project_root;
  const gsapPath = firstExisting(projectRoot, GSAP_CANDIDATES);
  const chromePath = firstExisting(projectRoot, CHROME_CANDIDATES, true);
  const playwrightPath = firstExisting(projectRoot, PLAYWRIGHT_CANDIDATES);
  if (!gsapPath || !chromePath || !playwrightPath) throw new Error('assembled clock dependencies are unavailable');
  if (!Array.isArray(request.entries) || !request.entries.length) throw new Error('entries are required');
  const gsapBytes = fs.readFileSync(gsapPath);
  const require = createRequire(import.meta.url);
  const {chromium} = require(playwrightPath);
  const browser = await chromium.launch({executablePath: chromePath, headless: true});
  const entries = [];
  try {
    for (const entry of request.entries) {
      const directory = path.resolve(projectRoot, entry.entry_directory);
      if (!fs.existsSync(path.join(directory, 'index.html'))) throw new Error('assembled entry index.html is missing');
      const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hf-clock-'));
      let server, page;
      try {
        fs.cpSync(directory, temp, {recursive: true});
        const requestedPort = 31000 + Math.floor(Math.random() * 1000);
        let port;
        server = spawn(process.execPath, [path.join(projectRoot, HYPERFRAMES), 'preview', temp,
          '--foreground', '--json', '--no-open', '--port=' + requestedPort], {
          env: {...process.env, HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1'},
          stdio: ['ignore', 'pipe', 'pipe']});
        await new Promise((resolve, reject) => {
          let buffer = '';
          const timer = setTimeout(() => reject(new Error('HyperFrames preview readiness timeout')), 30000);
          const fail = error => {clearTimeout(timer); reject(error);};
          server.once('error', fail);
          server.once('exit', code => fail(new Error('preview exited before readiness: ' + code)));
          const consume = chunk => {
            buffer += chunk;
            const lines = buffer.split('\n'); buffer = lines.pop();
            for (const line of lines) {
              let envelope; try {envelope = JSON.parse(line);} catch {continue;}
              if (envelope.operation !== 'start') continue;
              const ready = envelope.result;
              if (envelope.ok && ready?.ready && Number.isInteger(ready.port) && ready.port > 0 && ready.port < 65536) {
                port = ready.port; clearTimeout(timer); resolve();
              } else if (!envelope.ok) fail(new Error(envelope.error?.message || 'preview start failed'));
            }
          };
          server.stdout.on('data', consume); server.stderr.on('data', consume);
        });
        const base = `http://127.0.0.1:${port}`;
        page = await browser.newPage({viewport: {width: 1080, height: 1920}});
        await page.evaluate(validateHostStyles, fs.readFileSync(path.join(temp, 'index.html'), 'utf8'));
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          const url = route.request().url();
          if (/gsap[^/]*\.js(\?|$)/.test(url)) return route.fulfill({body: gsapBytes, contentType: 'application/javascript'});
          if (url.startsWith(base + '/') || url.startsWith(`http://localhost:${port}/`)) return route.continue();
          return route.abort();
        });
        const config = await (await page.request.get(base + '/__hyperframes_config')).json();
        if (typeof config.projectName !== 'string' || !config.projectName) throw new Error('preview project identity is missing');
        await page.goto(base + '/api/projects/' + encodeURIComponent(config.projectName) + '/preview/comp/index.html',
          {waitUntil: 'domcontentloaded', timeout: 15000});
        try {
          await page.waitForFunction(route => window.__player?.renderSeek && window.__timelines?.[route]?.time &&
            document.querySelector('[data-hf-authored-id="root"]'),
            entry.route.replace(/^hyperframes\//, ''), {timeout: 10000});
          await page.evaluate(async () => {
            await document.fonts.ready;
            await Promise.all([...document.images].map(image => image.decode()));
          });
        } catch (error) {
          const actual = await page.evaluate(() => ({player: !!window.__player,
            timelines: Object.keys(window.__timelines || {}),
            authored_roots: document.querySelectorAll('[data-hf-authored-id="root"]').length}));
          throw new Error('native runtime readiness failed for ' + entry.route + ': ' + error.message +
            '; observed=' + JSON.stringify(actual) + '; ' + errors.slice(0, 3).join('; '));
        }
        const observed = await page.evaluate(async ({sample, entry, fps}) => (0, eval)('(' + sample + ')')(entry, fps),
          {sample: SAMPLE.toString(), entry, fps: FPS});
        entries.push({...observed, requested_duration: entry.duration, mount_start: entry.start, declared_events: entry.events});
      } finally {
        if (page) await page.close();
        if (server && server.exitCode === null) {
          const stopped = once(server, 'exit');
          const timer = setTimeout(() => server.kill('SIGKILL'), 2000);
          server.kill('SIGTERM');
          try {await stopped;} finally {clearTimeout(timer);}
        }
        fs.rmSync(temp, {recursive: true, force: true});
      }
    }
    return {ok: true, entries};
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  readStdinJson().then(runCheck).then(result => process.stdout.write(JSON.stringify(result) + '\n')).catch(error => {
    process.stderr.write(String(error.stack || error) + '\n'); process.exitCode = 1;
  });
}

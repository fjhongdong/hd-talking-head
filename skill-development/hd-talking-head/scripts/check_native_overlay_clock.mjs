#!/usr/bin/env node
// Reconstructed assembled-native-clock checker for the HD talking-head skill.
//
// Reads {project_root, work_directory, python_executable,
// entries: [{entry_directory, route, duration, start, events, timeout_ms}]}.
// For every assembled entry it loads the host HTML
// in the actual pinned HyperFrames preview runtime in headless system Chrome,
// blocks all non-loopback network access, then seeks the authored gsap timeline
// over the mount and adjacent boundary frames on the approved 24 fps clock and
// records the observed entry/exit times, timeline duration, peak visible
// texts, and whether the temporary data-duration attribute was removed by the
// post-handoff snippet. No media export, no online access, no source edits.
//
// Prints {"ok": true, "entries": [...]} for overlay_alignment._assembled_clocks.

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import {spawn} from "node:child_process";
import { createRequire } from "node:module";
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';
import {createHash} from 'node:crypto';

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
  let hold = null;
  if (Number.isFinite(total) && total > 0 && total < entry.duration - tolerance
      && route === 'grid-card-assemble') {
    const values = JSON.parse(mount.getAttribute('data-variable-values') || '{}');
    const events = entry.events.filter(event => event.kind === 'reveal');
    const labels = [...root.querySelectorAll('.gca-label')];
    // The pinned primitive's public exit=none intentionally has no OUT tween.
    // Its standard mount duration, not an empty tween, owns the still tail.
    if ((values.exit ?? 'none') === 'none' && events.length && labels.length === events.length
        && labels.every((label, i) => label.textContent.trim() === events[i].text)) {
      const tile = Math.min(.65, Math.max(.2, entry.duration - .15));
      const lastLanding = Math.max(...events.map(event => event.time - entry.start)) + tile;
      const first = Math.ceil((entry.start + lastLanding) * fps - 1e-6);
      const last = Math.ceil((entry.start + entry.duration) * fps - 1e-6) - 1;
      // The pinned assembler moves authored mount timing to its standard
      // data-hf-authored-* attributes; the native root handoff is temporary.
      const mountDuration = mount.getAttribute('data-duration') ?? mount.getAttribute('data-hf-authored-duration');
      if (Math.abs(total - lastLanding) > 1e-6 || last - first + 1 < Math.ceil(.5 * fps)
          || mountDuration === null || !Number.isFinite(Number(mountDuration))
          || Math.abs(Number(mountDuration) - entry.duration) > 1e-6) {
        throw new Error('native grid hold does not follow its complete action and reading window: ' +
          JSON.stringify({total, lastLanding, first, last, mount_duration: mount.getAttribute('data-duration'),
            authored_duration: mount.getAttribute('data-hf-authored-duration')}));
      }
      hold = {first_frame: first, last_frame: last, frames_checked: 0, labels,
        samples: [...new Set([first, Math.floor((first + last) / 2), last])].map(frame => frame / fps)};
    }
  }
  if (!Number.isFinite(total) || !Number.isFinite(hostTotal) || total <= 0
      || (!hold && Math.abs(total - entry.duration) > tolerance)
      || hostTotal < entry.start + entry.duration - tolerance) {
    throw new Error('native duration differs from the declared clock: ' + JSON.stringify({native_duration: total, requested_duration: entry.duration, host_duration: hostTotal, mount_start: entry.start}));
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
  // Keep global player coordinates, but inspect only this mount and one frame
  // on either side. A long host must not multiply unrelated seek work.
  const firstFrame = Math.max(0, Math.floor(entry.start * fps) - 1);
  const lastFrame = Math.min(Math.ceil(hostTotal * fps), Math.ceil((entry.start + entry.duration) * fps) + 1);
  let sampledFrames = 0;
  let heldState;
  for (let frame = firstFrame; frame <= lastFrame; frame++) {
    const time = Math.min(frame / fps, hostTotal);
    await seek(time);
    const count = texts(root).filter(item => visible(item.element, item.rect)).length;
    if (count) {entryFrame ??= frame; exitFrame = frame; peak = Math.max(peak, count);}
    if (hold && frame >= hold.first_frame && frame <= hold.last_frame) {
      for (const label of hold.labels) {
        const range = document.createRange(); range.selectNodeContents(label);
        if (!visible(label, range.getBoundingClientRect())) throw new Error('native grid hold hides a required label');
      }
      const state = JSON.stringify([...root.querySelectorAll('.gca-card,.gca-icon path')].map(element => {
        const style = getComputedStyle(element), rect = element.getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height, style.opacity, style.transform, style.filter,
          style.clipPath, element.getAttribute('stroke-dashoffset')];
      }));
      heldState ??= state;
      if (heldState !== state) throw new Error('native grid final state changes during its hold');
      hold.frames_checked++;
    }
    sampledFrames++;
    if (window.__hdClockProgress && (sampledFrames === 1 || sampledFrames % fps === 0)) {
      await window.__hdClockProgress({checked_frames: sampledFrames, frame});
    }
  }
  if (!peak) throw new Error('native content is never visible');
  let holdCheck = null;
  if (hold) {
    if (hold.frames_checked !== hold.last_frame - hold.first_frame + 1) throw new Error('native grid hold sampling is incomplete');
    const rect = mount.getBoundingClientRect();
    const clip = {x: rect.left, y: rect.top, width: rect.width, height: rect.height};
    if (clip.x < 0 || clip.y < 0 || clip.width <= 0 || clip.height <= 0
        || clip.x + clip.width > 1080 || clip.y + clip.height > 1920) throw new Error('native grid hold mount is outside its canvas');
    holdCheck = {first_frame: hold.first_frame, last_frame: hold.last_frame,
      frames_checked: hold.frames_checked, samples: hold.samples, clip};
  }
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
    authored_root_id: root.getAttribute('data-hf-authored-id'), visibility_checks: visibilityChecks,
    hold_check: holdCheck,
    sampled_frames: sampledFrames, sampling_window: {first_frame: firstFrame, last_frame: lastFrame}};
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

function writeJson(directory, name, value) {
  const target = path.join(directory, name);
  fs.writeFileSync(target + '.tmp', JSON.stringify(value));
  fs.renameSync(target + '.tmp', target);
}

export async function runCheck(request) {
  const projectRoot = request.project_root;
  const gsapPath = firstExisting(projectRoot, GSAP_CANDIDATES);
  const chromePath = firstExisting(projectRoot, CHROME_CANDIDATES, true);
  const playwrightPath = firstExisting(projectRoot, PLAYWRIGHT_CANDIDATES);
  if (!gsapPath || !chromePath || !playwrightPath) throw new Error('assembled clock dependencies are unavailable');
  if (!Array.isArray(request.entries) || !request.entries.length) throw new Error('entries are required');
  if (!request.entries.every(entry => Number.isFinite(entry.start) && entry.start >= 0 &&
      Number.isFinite(entry.duration) && entry.duration > 0 && Number.isInteger(entry.timeout_ms) &&
      entry.timeout_ms > 0 && entry.timeout_ms <= 300000)) throw new Error('invalid native clock window or deadline');
  if (typeof request.work_directory !== 'string' || !path.isAbsolute(request.work_directory) ||
      !fs.statSync(request.work_directory).isDirectory() || fs.readdirSync(request.work_directory).length) {
    throw new Error('native clock check requires an empty owned work directory');
  }
  const work = request.work_directory;
  if (typeof request.python_executable !== 'string' || !path.isAbsolute(request.python_executable)) {
    throw new Error('native clock check requires the selected Python executable');
  }
  const gsapBytes = fs.readFileSync(gsapPath);
  const require = createRequire(import.meta.url);
  const {chromium} = require(playwrightPath);
  let browserServer, browser, activePage, activeServer, cancelled;
  let progress = {phase: 'browser_startup', checker_pid: process.pid};
  const update = (phase, values = {}) => {
    progress = {...progress, phase, ...values};
    writeJson(work, 'progress.json', progress);
  };
  const cancel = error => {
    cancelled ||= error;
    if (activeServer?.pid && activeServer.exitCode === null) activeServer.kill('SIGTERM');
    if (activePage) void activePage.close().catch(() => {});
    if (browserServer) void browserServer.close().catch(() => {});
  };
  const stopped = () => cancel(new Error('native clock check was terminated: ' + JSON.stringify(progress)));
  const checkpoint = () => {if (cancelled) throw cancelled;};
  process.on('SIGTERM', stopped);
  process.on('SIGINT', stopped);
  update('browser_startup');
  const entries = [];
  try {
    // The child registers its group before exec, closing the cancellation
    // window while launchServer is still waiting for Chrome to become ready.
    writeJson(work, 'browser-launch.json', {parent_pid: process.pid, work_directory: work, executable: chromePath});
    const launcher = path.join(work, 'browser-launch.sh');
    const shellQuote = value => "'" + value.replaceAll("'", "'\\''") + "'";
    fs.writeFileSync(launcher, '#!/bin/sh\nexec ' + [request.python_executable,
      path.join(projectRoot, 'skill-development/hd-talking-head/scripts/clock_browser_exec.py'),
      path.join(work, 'browser-launch.json')].map(shellQuote).join(' ') + ' "$@"\n', {mode: 0o700});
    browserServer = await chromium.launchServer({executablePath: launcher, headless: true,
      timeout: 30000, handleSIGTERM: false, handleSIGINT: false, handleSIGHUP: false});
    const pid = browserServer.process().pid;
    const registered = JSON.parse(fs.readFileSync(path.join(work, 'browser.json'), 'utf8'));
    if (registered.pid !== pid) throw new Error('Chrome process differs from its launch registration');
    checkpoint();
    browser = await chromium.connect(browserServer.wsEndpoint(), {timeout: 10000});
    checkpoint();
    for (const [index, entry] of request.entries.entries()) {
      const directory = path.resolve(projectRoot, entry.entry_directory);
      if (!fs.existsSync(path.join(directory, 'index.html'))) throw new Error('assembled entry index.html is missing');
      const temp = fs.mkdtempSync(path.join(work, 'entry-'));
      let server, page;
      update('entry_startup', {entry_index: index, route: entry.route, checked_frames: 0, frame: null, preview_pid: null});
      const deadline = setTimeout(() => cancel(new Error('native clock entry deadline exceeded: ' + JSON.stringify(progress))), entry.timeout_ms);
      try {
        fs.cpSync(directory, temp, {recursive: true});
        checkpoint();
        const requestedPort = 31000 + Math.floor(Math.random() * 1000);
        let port;
        server = activeServer = spawn(process.execPath, [path.join(projectRoot, HYPERFRAMES), 'preview', temp,
          '--foreground', '--json', '--no-open', '--port=' + requestedPort], {
          env: {...process.env, HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1',
            XDG_STATE_HOME: path.join(work, 'preview-state')},
          stdio: ['ignore', 'pipe', 'pipe']});
        update('preview_startup', {preview_pid: server.pid});
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
        checkpoint();
        const base = `http://127.0.0.1:${port}`;
        page = activePage = await browser.newPage({viewport: {width: 1080, height: 1920}});
        checkpoint();
        await page.exposeFunction('__hdClockProgress', values => update('sampling', values));
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
        update('runtime_readiness');
        await page.goto(base + '/api/projects/' + encodeURIComponent(config.projectName) + '/preview/comp/index.html',
          {waitUntil: 'domcontentloaded', timeout: 15000});
        checkpoint();
        try {
          await page.waitForFunction(route => window.__player?.renderSeek && window.__timelines?.[route]?.time &&
            document.querySelector('[data-hf-authored-id="root"]'),
            entry.route.replace(/^hyperframes\//, ''), {timeout: 10000});
          update('fonts_and_images');
          await page.evaluate(async () => {
            await document.fonts.ready;
            await Promise.all([...document.images].map(image => image.decode()));
          });
        } catch (error) {
          checkpoint();
          const actual = await page.evaluate(() => ({player: !!window.__player,
            timelines: Object.keys(window.__timelines || {}),
            authored_roots: document.querySelectorAll('[data-hf-authored-id="root"]').length}));
          throw new Error('native runtime readiness failed for ' + entry.route + ': ' + error.message +
            '; observed=' + JSON.stringify(actual) + '; ' + errors.slice(0, 3).join('; '));
        }
        checkpoint();
        update('sampling');
        const observed = await page.evaluate(async ({sample, entry, fps}) => (0, eval)('(' + sample + ')')(entry, fps),
          {sample: SAMPLE.toString(), entry, fps: FPS});
        if (observed.hold_check) {
          let first;
          const hashes = [];
          for (const time of observed.hold_check.samples) {
            await page.evaluate(async time => {
              await window.__player.renderSeek(time, {exact: true});
              if (window.__hfWaitForSeekCompletion) await window.__hfWaitForSeekCompletion();
            }, time);
            const actual = await page.screenshot({clip: observed.hold_check.clip, omitBackground: true});
            first ??= actual;
            if (!first.equals(actual)) throw new Error('native grid held pixels differ between actual frames');
            hashes.push({time, sha256: createHash('sha256').update(actual).digest('hex')});
          }
          observed.hold_check.pixel_samples = hashes;
        }
        checkpoint();
        entries.push({...observed, requested_duration: entry.duration, mount_start: entry.start, declared_events: entry.events});
        update('entry_complete', {checked_frames: observed.sampled_frames});
      } catch (error) {
        throw cancelled || new Error('native clock check failed at ' + JSON.stringify(progress) + ': ' + error.message);
      } finally {
        clearTimeout(deadline);
        if (page) await page.close().catch(() => {});
        activePage = undefined;
        if (server?.pid && server.exitCode === null) {
          const exited = once(server, 'exit');
          const timer = setTimeout(() => server.kill('SIGKILL'), 2000);
          server.kill('SIGTERM');
          try {await exited;} finally {clearTimeout(timer);}
        }
        activeServer = undefined;
        fs.rmSync(temp, {recursive: true, force: true});
      }
    }
    return {ok: true, entries};
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (browserServer) await browserServer.close().catch(() => {});
    process.off('SIGTERM', stopped);
    process.off('SIGINT', stopped);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  readStdinJson().then(runCheck).then(result => process.stdout.write(JSON.stringify(result) + '\n')).catch(error => {
    process.stderr.write(String(error.stack || error) + '\n'); process.exitCode = 1;
  });
}

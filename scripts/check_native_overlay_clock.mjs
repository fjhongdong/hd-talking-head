#!/usr/bin/env node
// Reconstructed assembled-native-clock checker for the HD talking-head skill.
//
// Reads {"project_root": ..., "entries": [{entry_directory, route, duration,
// start, events}]} on stdin. For every assembled entry it loads the host HTML
// in a real headless system-Chrome page, mounts the native component exactly
// the way the HyperFrames assembler does (the native file's <template> content
// is cloned into the host mount and its scripts run in order), serves every
// gsap request from the pinned central copy (the local vendor path and the
// component CDN alike) and blocks all other network access, then seeks the
// REAL native gsap timeline frame by frame on the approved 24 fps clock and
// records the observed entry/exit times, timeline duration, peak visible
// texts, and whether the temporary data-duration attribute was removed by the
// post-handoff snippet. No media export, no online access, no source edits.
//
// Prints {"ok": true, "entries": [...]} for overlay_alignment._assembled_clocks.

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { createRequire } from "node:module";

const GSAP_CANDIDATES = [
  "参考项目/B-roll开源方案/hyperframes/skills/talking-head-recut/assets/vendor/gsap.min.js",
  "参考项目/B-roll开源方案/hyperframes/skills/music-to-video/references/motion-primitives/assets/gsap.min.js",
];
const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const PLAYWRIGHT_CANDIDATES = [
  "skill-development/runtime/adu-native/node_modules/playwright-core",
];
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

const SAMPLE = (route, fps) => {
  const log = [];
  try {
    const mount = document.querySelector(".mount");
    if (!mount) throw new Error("host mount is missing");
    const doc = new DOMParser().parseFromString(window.__native_html__, "text/html");
    const template = doc.querySelector("template");
    if (!template) throw new Error("native template is missing");
    const scripts = [...template.content.querySelectorAll("script")]
      .filter((s) => !s.src && s.textContent.trim())
      .map((s) => s.textContent);
    mount.appendChild(template.content.cloneNode(true));
    if (!document.getElementById("root")) throw new Error("native root did not mount");
    for (const source of scripts) {
      (0, eval)(source);
    }
    const timeline = (window.__timelines || {})[route];
    if (!timeline) throw new Error("native timeline is not registered: " + route);
    const total = timeline.duration();
    const frames = Math.max(1, Math.ceil(total * fps));
    let entryFrame = null;
    let exitFrame = null;
    let peak = 0;
    for (let frame = 0; frame <= frames; frame += 1) {
      timeline.seek(frame / fps, false);
      let visible = 0;
      for (const el of mount.querySelectorAll("*")) {
        const style = window.getComputedStyle(el);
        if (style.visibility === "hidden") continue;
        if (parseFloat(style.opacity || "1") <= 0.01) continue;
        if ((el.textContent || "").trim()) visible += 1;
      }
      if (visible > 0) {
        if (entryFrame === null) entryFrame = frame;
        exitFrame = frame;
        peak = Math.max(peak, visible);
      }
    }
    timeline.seek(0, false);
    const nativeRoot = document.getElementById("root");
    const stage = document.querySelector(".stage");
    return {
      ok: true,
      route,
      timeline_duration: total,
      entry_time: entryFrame === null ? null : entryFrame / fps,
      exit_time: exitFrame === null ? null : exitFrame / fps,
      peak_visible_texts: peak,
      temporary_duration_removed: nativeRoot ? !nativeRoot.hasAttribute("data-duration") : null,
      host_duration: stage ? stage.getAttribute("data-duration") : null,
      host_start: mount.getAttribute("data-start"),
    };
  } catch (error) {
    return { ok: false, route, error: String((error && error.message) || error) };
  }
};

async function main() {
  const request = await readStdinJson();
  const projectRoot = request.project_root;
  const gsapPath = firstExisting(projectRoot, GSAP_CANDIDATES);
  const chromePath = firstExisting(projectRoot, CHROME_CANDIDATES, true);
  const playwrightPath = firstExisting(projectRoot, PLAYWRIGHT_CANDIDATES);
  if (!gsapPath || !chromePath || !playwrightPath) {
    throw new Error("assembled clock dependencies are unavailable (gsap/chrome/playwright)");
  }
  const gsapBytes = fs.readFileSync(gsapPath);
  const require = createRequire(import.meta.url);
  const { chromium } = require(playwrightPath);
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const entries = [];
  try {
    for (const entry of request.entries) {
      const directory = path.isAbsolute(entry.entry_directory)
        ? entry.entry_directory
        : path.join(projectRoot, entry.entry_directory);
      const nativeHtml = fs.readFileSync(path.join(directory, "native.html"), "utf8");
      const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
      await page.route("**/*", (route) => {
        const url = route.request().url();
        if (/gsap[^/]*\.js(\?|$)/.test(url)) {
          route.fulfill({ body: gsapBytes, contentType: "application/javascript" });
        } else if (url.startsWith("file://")) {
          route.continue();
        } else {
          route.abort();
        }
      });
      await page.goto("file://" + path.join(directory, "index.html"), { waitUntil: "load" });
      await page.evaluate((html) => { window.__native_html__ = html; }, nativeHtml);
      const observed = await page.evaluate(
        ({ sample, route, fps }) => eval("(" + sample + ")")(route, fps),
        { sample: String(SAMPLE), route: entry.route.replace(/^hyperframes\//, ""), fps: FPS });
      await page.close();
      if (!observed.ok) throw new Error(observed.error);
      entries.push({
        ...observed,
        requested_duration: entry.duration,
        mount_start: entry.start,
        declared_events: entry.events,
      });
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ ok: true, entries }) + "\n");
}

main().catch((error) => {
  process.stderr.write(String((error && error.stack) || error) + "\n");
  process.exit(1);
});

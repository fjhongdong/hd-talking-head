// Usage (can be run from any directory; the script chdirs to demo/):
//   node render.mjs events                  → events.json (DUR + all hits, for music.py)
//   node render.mjs stills 1.9 3.1 ...      → stills/t_*.png (STILLS_DIR=out/check changes the output dir)
//   node render.mjs video [workers]         → out/seg_*.mp4 + out/list.txt (then run sh finish.sh to concatenate + mix)
//   SEGS=5 node render.mjs video 6          → re-renders only segment 5 of 6 equal parts (end of film 124.0–148.8 s)
//   CHROME=/path/to/chrome-headless-shell overrides the browser path
import { chromium } from 'playwright-core';
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
process.chdir(path.dirname(fileURLToPath(import.meta.url)));
const EXE_DEFAULT = `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
const EXE = process.env.CHROME || (fs.existsSync(EXE_DEFAULT) ? EXE_DEFAULT : undefined);   // undefined → playwright's own default
const URL = 'file://' + path.resolve('index.html');
const FPS = 30;
const mode = process.argv[2];

async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on('console', m => { if (m.type() === 'error') console.error('[page]', m.text()); });
  page.on('pageerror', e => console.error('[pageerror]', e.message));
  await page.goto(URL);
  await page.waitForFunction(() => window.READY === true, null, { timeout: 60000 });
  return page;
}

const browser = await chromium.launch({ executablePath: EXE, args: ['--font-render-hinting=none', '--force-color-profile=srgb'] });
if (mode === 'stills') {
  const SD = process.env.STILLS_DIR || 'stills';
  fs.mkdirSync(SD, { recursive: true });
  const page = await openPage(browser);
  for (const ts of process.argv.slice(3)) {
    await page.evaluate(t => window.render(t), parseFloat(ts));
    await page.screenshot({ path: `${SD}/t_${ts}.png` });
  }
} else if (mode === 'events') {
  const page = await openPage(browser);
  const ev = await page.evaluate(() => ({ dur: window.DUR, ev: window.EV }));
  fs.writeFileSync('events.json', JSON.stringify(ev, null, 0));
  console.log('events', ev.ev.length, 'dur', ev.dur.toFixed(2));
} else if (mode === 'video') {
  const W = parseInt(process.argv[3] || '6');
  fs.mkdirSync('out', { recursive: true });
  const probe = await openPage(browser); const TOTAL = Math.round(FPS * await probe.evaluate(() => window.DUR)); await probe.close();
  const per = Math.ceil(TOTAL / W);
  const t0 = Date.now();
  // SEGS=5 re-renders only segment 5 (W equal parts; use with finish.sh, concatenating the old segments, e.g. when only the ending changed)
  const SEGS = process.env.SEGS ? process.env.SEGS.split(',').map(Number) : null;
  await Promise.all([...Array(W)].map(async (_, w) => {
    if (SEGS && !SEGS.includes(w)) return;
    const a = w * per, b = Math.min(TOTAL, a + per);
    const page = await openPage(browser);
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '12', '-pix_fmt', 'yuv420p', `out/seg_${w}.mp4`]);
    for (let f = a; f < b; f++) {
      await page.evaluate(t => window.render(t), f / FPS);
      const buf = await page.screenshot({ type: 'png' });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (w === (SEGS ? SEGS[0] : 0) && (f - a) % 30 === 0) console.log(`w${w} ${f - a}/${b - a}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  }));
  fs.writeFileSync('out/list.txt', [...Array(W)].map((_, w) => `file 'seg_${w}.mp4'`).join('\n'));
  console.log('done', ((Date.now() - t0) / 1000).toFixed(0) + 's');
}
await browser.close();

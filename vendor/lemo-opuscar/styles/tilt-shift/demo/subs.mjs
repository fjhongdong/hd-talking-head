// Export the subtitle timeline from the page (same data as the burned-in subtitles): node styles/tilt-shift/demo/subs.mjs → demo/cues.json
import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
import { openDemo, closeServer } from '../../../core/render/page.mjs';
const dir = path.dirname(fileURLToPath(import.meta.url));
const { browser, page } = await openDemo(dir, { q: 'noev' });
const subs = await page.evaluate(() => window.SUBS.map(s => ({ t0: +s.t0.toFixed(3), t1: +s.t1.toFixed(3), text: s.text })));
fs.writeFileSync(path.join(dir, 'cues.json'), JSON.stringify(subs, null, 1));
console.log('cues', subs.length); await browser.close(); closeServer();

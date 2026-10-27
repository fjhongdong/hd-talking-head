// Export the burned-in subtitle timetable → out/subs.json (then core/render/srt.py converts it to .srt)
import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
import { openDemo, closeServer } from '../../../../core/render/page.mjs';
const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { browser, page } = await openDemo(dir);
const subs = await page.evaluate(() => window.SUBS.map(s => ({ t0: +s.t0.toFixed(2), t1: +s.t1.toFixed(2), text: s.text })));
fs.writeFileSync(path.join(dir, 'out/subs.json'), JSON.stringify(subs, null, 1)); console.log('subs', subs.length);
await browser.close(); closeServer();

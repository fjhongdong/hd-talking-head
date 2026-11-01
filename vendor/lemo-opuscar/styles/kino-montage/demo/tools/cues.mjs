// Subtitle cues straight from the page (the same table that burns them in) -> audio/cues.json, then
// every cue is measured: one line per language, never wider than the frame minus margins.
//   node <demo>/tools/cues.mjs          (run from the library root)
import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
const LIB = process.env.LIB || process.cwd();
const { openDemo, closeServer } = await import(path.join(LIB, 'core/render/page.mjs'));
const HERE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { browser, page } = await openDemo(HERE);
const subs = await page.evaluate(() => {
  const c = document.createElement('canvas').getContext('2d');
  return window.SUBS.map(s => { c.font = '700 40px SC'; const wz = c.measureText(s.zh).width; c.font = '500 28px Osw'; c.letterSpacing = '1px'; const we = c.measureText(s.en).width; return { ...s, wz, we }; });
});
let bad = 0;
const cues = subs.map(s => { if (88 + Math.max(s.wz, s.we) > 1880) { bad++; console.log('TOO WIDE', s.id, s.zh, s.en); } return { t0: +s.t0.toFixed(3), t1: +s.t1.toFixed(3), text: `${s.zh}\n${s.en}` }; });
fs.writeFileSync(path.join(HERE, 'audio/cues.json'), JSON.stringify(cues, null, 1));
console.log('cues', cues.length, bad ? `${bad} too wide` : 'all one line per language');
await browser.close(); closeServer(); process.exit(bad ? 1 : 0);

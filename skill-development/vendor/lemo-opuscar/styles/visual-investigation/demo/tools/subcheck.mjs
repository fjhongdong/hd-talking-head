// Subtitle check: one line per language.
//   node tools/subcheck.mjs [path/to/film.srt]
// 1. In the page (window.SUBCHECK), the widths of the Chinese and English lines are measured in the burned-in font and must be ≤ the 1500 px safe width (nowrap, never wrapped).
// 2. Duration: each cue ≥ 1.8 s (film.json).
// 3. .srt: exactly two lines per cue, Chinese on top, English below.
import path from 'path'; import fs from 'fs'; import { fileURLToPath } from 'url';
const HERE = path.dirname(fileURLToPath(import.meta.url)), DEMO = path.resolve(HERE, '..');
const LIB = process.env.LIB || path.resolve(DEMO, '../../..');
const { openDemo, closeServer } = await import(path.join(LIB, 'core/render/page.mjs'));
const { browser, page } = await openDemo(DEMO, { w: 1920, h: 1080 });
const rows = await page.evaluate(() => window.SUBCHECK());
await browser.close(); closeServer();
let bad = 0;
for (const r of rows) { if (!r.ok) bad++; console.log(`${r.ok ? 'OK ' : 'BAD'} #${String(r.i + 1).padStart(2)}  zh ${String(r.wz).padStart(4)} px  en ${String(r.we).padStart(4)} px  ${r.zh} | ${r.en}`); }
const film = JSON.parse(fs.readFileSync(path.join(DEMO, 'film.json'), 'utf8'));
film.subs.forEach(([a, b], i) => { if (b - a < 1.8 - 1e-6) { bad++; console.log(`BAD #${i + 1} on screen ${(b - a).toFixed(2)} s < 1.8 s`); } });
const srt = process.argv[2];
if (srt && fs.existsSync(srt)) {
  const blocks = fs.readFileSync(srt, 'utf8').trim().split(/\r?\n\r?\n/); const han = s => /\p{Script=Han}/u.test(s);
  for (const b of blocks) { const L = b.split(/\r?\n/), text = L.slice(2); if (text.length !== 2 || !han(text[0]) || han(text[1])) { bad++; console.log(`BAD srt cue ${L[0]}: ${JSON.stringify(text)}`); } }
  console.log(`srt: ${blocks.length} cues checked`);
}
console.log(bad ? `subcheck: ${bad} problems` : `subcheck: OK (${rows.length} cues, each language on one line)`);
process.exit(bad ? 1 : 0);

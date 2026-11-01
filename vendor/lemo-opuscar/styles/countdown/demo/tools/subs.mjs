// Export subtitles from the page (audio/cues.json: one Chinese line + one English line) and check that none of them wraps in the transcript box.
// Usage (library root): node films/<name>/demo/tools/subs.mjs films/<name>/demo
import fs from 'fs'; import path from 'path';
import { openDemo, closeServer } from '../../../../core/render/page.mjs';
const dir = path.resolve(process.argv[2] || path.dirname(path.dirname(new URL(import.meta.url).pathname)));
const { browser, page } = await openDemo(dir);
const cues = await page.evaluate(() => window.CUES.map(c => ({ t0: c.t0, t1: c.t1, text: c.zh + '\n' + c.w.map(w => w[0]).join(' ') })));
const fit = await page.evaluate(() => window.SUBFIT());
await browser.close(); closeServer();
fs.writeFileSync(path.join(dir, 'audio/cues.json'), JSON.stringify(cues, null, 1));
let bad = 0;
for (const f of fit) if (!f.ok) { bad++; console.log('TOO WIDE', f); }
for (const c of cues) { const d = c.t1 - c.t0; if (d < 1.8) { bad++; console.log('TOO SHORT', c.t0, d.toFixed(2)); } }
console.log(`subs: ${cues.length} cues, ${bad ? bad + ' problem(s)' : 'all one line per language, all ≥ 1.8 s'}`);
process.exit(bad ? 1 : 0);

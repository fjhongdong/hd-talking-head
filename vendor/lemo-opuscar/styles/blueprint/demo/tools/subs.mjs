// Read window.SUBS from the page and export subs.json (the srt and the burned-in subtitles share the same data)
import { chromium } from 'playwright-core'; import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.resolve(HERE, '../../../..');
const { serve } = await import(path.join(ROOT, 'core/render/serve.mjs')); const { EXE, ARGS } = await import(path.join(ROOT, 'core/render/browser.mjs'));
const { server, port } = await serve(ROOT); const b = await chromium.launch({ executablePath: EXE, args: ARGS }); const p = await b.newPage();
await p.goto(`http://127.0.0.1:${port}/styles/blueprint/demo/index.html`); await p.waitForFunction(() => window.READY === true);
const subs = await p.evaluate(() => window.SUBS); fs.writeFileSync(path.join(HERE, '../subs.json'), JSON.stringify(subs, null, 1));
console.log(subs.map(s => `${s.t0.toFixed(2)}-${s.t1.toFixed(2)} ${s.text}`).join('\n')); await b.close(); server.close();

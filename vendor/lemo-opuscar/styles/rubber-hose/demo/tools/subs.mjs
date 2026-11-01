// Export the title-card timeline (same data as the burned-in subtitles): node styles/rubber-hose/demo/tools/subs.mjs → demo/out/cues.json
import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
import { openDemo, closeServer } from '../../../../core/render/page.mjs';
const dir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { browser, page } = await openDemo(dir);
const subs = await page.evaluate(() => window.SUBS);
fs.mkdirSync(path.join(dir, 'out'), { recursive: true });
fs.writeFileSync(path.join(dir, 'out', 'cues.json'), JSON.stringify(subs, null, 1));
console.log('cues', subs.length);
await browser.close(); closeServer();

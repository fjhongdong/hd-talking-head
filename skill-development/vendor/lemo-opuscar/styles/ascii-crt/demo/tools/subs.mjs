// Export the page's window.SUBS → out/subs.json (same timings as the on-screen log panel)
import fs from 'fs'; import path from 'path';
import { openDemo, closeServer } from '../../../../core/render/page.mjs';
const dir = process.argv[2];
const { browser, page } = await openDemo(dir);
const subs = await page.evaluate(() => window.SUBS);
fs.mkdirSync(path.join(dir, 'out'), { recursive: true });
fs.writeFileSync(path.join(dir, 'out/subs.json'), JSON.stringify(subs, null, 1));
console.log('subs', subs.length);
await browser.close(); closeServer();

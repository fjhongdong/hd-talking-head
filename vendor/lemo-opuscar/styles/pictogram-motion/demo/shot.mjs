// Usage: node shot.mjs 1.0 6.8 20.1 ...  → stills/t_*.jpg ; add --sheet to tile them into one image
import { chromium } from 'playwright-core';
import path from 'path';
import { execSync } from 'child_process';
import fs from 'fs';
import { EXE } from '../../../core/render/browser.mjs';
// Language: LANGQ=ej (default, English/Japanese version) / LANGQ=zh (Chinese version). Run from the demo/ folder.
const LANGQ = process.env.LANGQ || 'ej';
const PY = fs.existsSync('../../../.venv/bin/python') ? '../../../.venv/bin/python' : '/usr/bin/python3';
const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const sheet = process.argv.includes('--sheet');
const b = await chromium.launch({ executablePath: EXE, args: ['--allow-file-access-from-files'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on('pageerror', (e) => console.error('[pageerror]', e.message));
p.on('console', (m) => { if (m.type() === 'error' && !/ERR_FILE_NOT_FOUND/.test(m.text())) console.error('[page]', m.text()); });
await p.goto('file://' + path.resolve('index.html') + '?lang=' + LANGQ);
await p.waitForFunction(() => window.READY === true, null, { timeout: 60000 });
const files = [];
for (const ts of args) {
  await p.evaluate((t) => window.render(t), parseFloat(ts));
  const f = `stills/t_${ts}.jpg`; files.push(f);
  await p.screenshot({ path: f, type: 'jpeg', quality: 85 });
}
await b.close();
if (sheet && files.length) {
  execSync(`${PY} sheet.py stills/sheet.jpg ${files.join(' ')}`);
  console.log('stills/sheet.jpg');
}

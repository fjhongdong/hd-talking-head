'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {validateBrief, htmlFor, frameState} = require('./semantic_state_renderer.cjs');

async function capture({brief: input, output, playwright, browser}) {
  // The exec shim authenticates with the watchdog before launching Chromium.
  if (!process.env.HD_BROWSER_SOCKET || !process.env.HD_BROWSER_TOKEN ||
      browser !== path.join(__dirname, 'relation_browser_shim.py')) {
    throw new Error('authenticated browser supervisor required');
  }
  const brief = validateBrief(input);
  for (const value of [output, playwright, browser]) {
    if (typeof value !== 'string' || !path.isAbsolute(value)) throw new Error('absolute paths required');
  }
  for (const value of [playwright, browser]) {
    if (!fs.lstatSync(value).isFile()) throw new Error('regular tool file required');
  }
  // Refuse symlinked output ancestors and never overwrite a previous run.
  let parent = path.dirname(output);
  for (;;) {
    if (!fs.lstatSync(parent).isDirectory() || fs.lstatSync(parent).isSymbolicLink()) throw new Error('invalid output parent');
    const next = path.dirname(parent);
    if (next === parent) break;
    parent = next;
  }
  fs.mkdirSync(output);
  let instance;
  try {
    instance = await require(playwright).chromium.launch({executablePath: browser, headless: true, timeout: 20000});
    const context = await instance.newContext({viewport: {width: 1080, height: 1920}, deviceScaleFactor: 1, offline: true});
    const problems = [];
    await context.route('**/*', route => { problems.push('external request'); return route.abort(); });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => problems.push(error.message));
    await page.setContent(htmlFor(brief), {waitUntil: 'load'});
    await page.evaluate(() => document.fonts.ready);
    const duration = brief.canvas.duration_in_frames;
    for (let frame = 0; frame <= duration; frame++) {
      const actual = await page.evaluate(value => window.seekFrame(value), frame);
      if (JSON.stringify(actual) !== JSON.stringify(frameState(brief, frame))) throw new Error(`frame state mismatch: ${frame}`);
      const name = frame === duration ? 'boundary.png' : `frame-${String(frame).padStart(6, '0')}.png`;
      await page.screenshot({path: path.join(output, name)});
      if (problems.length) throw new Error(problems.join('; '));
    }
    await instance.close();
    instance = null;
    return {frame_count: duration, width: 1080, height: 1920, fps: 24, status: 'maintenance_capture_only'};
  } finally {
    if (instance) await instance.close();
    // The caller owns staging cleanup. Never recursively delete an arbitrary
    // pathname here: an inode check cannot make a subsequent deletion atomic.
  }
}

module.exports = {capture};

if (require.main === module) {
  (async () => {
    const args = process.argv.slice(2);
    const options = {};
    if (args.length !== 6) throw new Error('output, playwright and browser arguments required');
    for (let index = 0; index < args.length; index += 2) {
      const flag = args[index];
      if (!['--output', '--playwright', '--browser'].includes(flag) ||
          Object.hasOwn(options, flag.slice(2))) throw new Error('invalid or duplicate argument');
      options[flag.slice(2)] = args[index + 1];
    }
    const limit = 4 * 1024 * 1024;
    const chunks = [];
    let size = 0;
    for (;;) {
      const chunk = Buffer.alloc(Math.min(65536, limit + 1 - size));
      const count = fs.readSync(0, chunk, 0, chunk.length, null);
      if (!count) break;
      size += count;
      if (size > limit) throw new Error('brief exceeds 4 MiB');
      chunks.push(chunk.subarray(0, count));
    }
    const source = new (require('node:util').TextDecoder)('utf-8', {fatal: true})
      .decode(Buffer.concat(chunks, size));
    const report = await capture({...options, brief: JSON.parse(source)});
    process.stdout.write(JSON.stringify(report) + '\n');
  })().catch(error => {
    const message = typeof error === 'string' ? error :
      (error && typeof error.message === 'string' ? error.message : 'unknown error');
    process.stderr.write(`semantic capture failed: ${message.slice(0, 500)}\n`);
    process.exitCode = 1;
  });
}

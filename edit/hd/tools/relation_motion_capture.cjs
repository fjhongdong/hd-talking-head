#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');

const KEYS = new Set(['html', 'output', 'duration', 'playwright', 'browser']);

function fail(message) { throw new Error(message); }

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    const token = argv[i];
    if (!token || !token.startsWith('--') || !KEYS.has(token.slice(2))) fail(`unknown argument: ${token || '<missing>'}`);
    const key = token.slice(2);
    if (Object.prototype.hasOwnProperty.call(out, key)) fail(`duplicate argument: --${key}`);
    if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) fail(`missing value: --${key}`);
    out[key] = argv[i + 1];
  }
  for (const key of KEYS) if (!out[key]) fail(`missing argument: --${key}`);
  if (!path.isAbsolute(out.html) || !path.isAbsolute(out.output) || !path.isAbsolute(out.playwright) || !path.isAbsolute(out.browser)) {
    fail('html, output, playwright, and browser must be absolute paths');
  }
  if (!/^\d+$/.test(out.duration)) fail('duration must be an integer');
  out.duration = Number(out.duration);
  if (!Number.isSafeInteger(out.duration) || out.duration < 48 || out.duration > 240) fail('duration must be between 48 and 240');
  return out;
}

function validateFrameState(state, expectedFrame, boundary) {
  if (!state || state.frame !== expectedFrame || state.artifact_alpha !== 1 || !Number.isFinite(state.compositor_alpha)) return false;
  if (state.compositor_alpha < 0 || state.compositor_alpha > 1) return false;
  const progress = ['source_progress', 'connector_progress', 'hub_progress'];
  if (progress.some(key => !Number.isFinite(state[key]) || state[key] < 0 || state[key] > 1)) return false;
  if (!boundary) return true;
  return state.compositor_alpha === 0 && progress.every(key => state[key] === 1);
}

function regularFile(p, label) {
  let st;
  try { st = fs.lstatSync(p); } catch { fail(`${label} does not exist: ${p}`); }
  if (!st.isFile()) fail(`${label} must be a regular file: ${p}`);
}

function validateInputs(args) {
  regularFile(args.html, 'html');
  regularFile(args.playwright, 'playwright module');
  regularFile(args.browser, 'browser');
  if (!fs.existsSync(path.dirname(args.output))) fail('output parent must exist');
  const parent = fs.lstatSync(path.dirname(args.output));
  if (!parent.isDirectory()) fail('output parent must be a directory');
  try { fs.lstatSync(args.output); fail(`output already exists: ${args.output}`); } catch (error) {
    if (error.message.startsWith('output already exists:')) throw error;
    if (error.code !== 'ENOENT') throw error;
  }
}

async function capture(args) {
  validateInputs(args);
  await fs.promises.mkdir(args.output);
  const playwright = require(args.playwright);
  let browser;
  let timer;
  const deadline = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('capture deadline exceeded')), 120000); });
  const work = (async () => {
    browser = await playwright.chromium.launch({ executablePath: args.browser, headless: true, timeout: 20000 });
    const context = await browser.newContext({ viewport: { width: 1080, height: 1920 }, offline: true });
    let routeAborts = 0;
    const problems = [];
    await context.route('**/*', async route => { routeAborts += 1; await route.abort(); });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
    page.on('console', message => { if (message.type() === 'error') problems.push(`consoleerror: ${message.text()}`); });
    page.on('request', request => problems.push(`network request: ${request.url()}`));
    page.on('requestfailed', request => problems.push(`network request failed: ${request.url()}`));
    const html = await fs.promises.readFile(args.html, 'utf8');
    await page.setContent(html, { waitUntil: 'load', timeout: 10000 });
    await page.evaluate(() => document.fonts.ready);
    const checkProblems = () => {
      if (routeAborts || problems.length) fail([...problems, routeAborts ? `network routes aborted: ${routeAborts}` : ''].filter(Boolean).join('; '));
    };
    for (let n = 0; n < args.duration; n += 1) {
      const state = await page.evaluate(frame => window.seekFrame(frame), n);
      if (!validateFrameState(state, n, false)) fail(`invalid frame state at ${n}`);
      await page.screenshot({ path: path.join(args.output, `frame-${String(n).padStart(6, '0')}.png`), type: 'png' });
      checkProblems();
    }
    const boundary = await page.evaluate(frame => window.seekFrame(frame), args.duration);
    if (!validateFrameState(boundary, args.duration, true)) fail('invalid boundary state');
    await page.screenshot({ path: path.join(args.output, 'boundary.png'), type: 'png' });
    checkProblems();
  })();
  try { await Promise.race([work, deadline]); }
  finally {
    clearTimeout(timer);
    if (browser) await browser.close().catch(() => {});
  }
}

if (require.main === module) {
  capture(parseArgs(process.argv.slice(2))).catch(error => { console.error(error.message); process.exitCode = 1; });
}

module.exports = { parseArgs, capture, validateFrameState };

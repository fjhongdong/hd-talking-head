'use strict';
// Executed from reviewed stdin by ReferenceProcessAdapter, not from cwd.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const {pipeline} = require('node:stream/promises');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const TEMPLATE_ID = 'html-video/frame-data-rollup';

function validateBrief(b) {
  const check = (ok, message) => { if (!ok) throw new Error(`DataRollup brief: ${message}`); };
  const exact = (value, keys, label) => check(value && typeof value === 'object' &&
    !Array.isArray(value) && Object.keys(value).sort().join('|') === keys.sort().join('|'), label);
  exact(b, ['schema_version', 'canvas', 'template_request', 'props'], 'unknown/missing fields');
  check(b.schema_version === 1, 'schema_version must be 1');
  exact(b.canvas, ['width', 'height', 'fps', 'duration_in_frames'], 'canvas fields');
  const c = b.canvas;
  check(c.width === 1080 && c.height === 1920 && c.fps === 24, 'requires native 1080x1920/24fps');
  // Last of eight bars starts at frame 21; retain at least two seconds to settle.
  check(Number.isSafeInteger(c.duration_in_frames) && c.duration_in_frames >= 72,
    'duration_in_frames must leave at least 72 frames for the entrance and reading');
  exact(b.props, ['data', 'accent', 'background', 'foreground'], 'all props must be explicit');
  exact(b.props.data, ['title', 'unit', 'items'], 'data fields must be explicit (no sample defaults)');
  const {title, unit, items} = b.props.data;
  const singleLine = s => typeof s === 'string' && !/[\x00-\x1f\x7f]/u.test(s);
  check(singleLine(title) && title.trim(), 'title must be a nonempty single line');
  check(singleLine(unit), 'unit must be explicit, empty string is allowed');
  check(Array.isArray(items) && items.length >= 3 && items.length <= 8, 'requires 3..8 items');
  for (const item of items) {
    exact(item, ['label', 'value'], 'item fields');
    check(singleLine(item.label) && item.label.trim(), 'label must be a nonempty single line');
    check(Number.isSafeInteger(item.value) && item.value >= 0, 'only nonnegative safe integers; no rounding');
  }
  exact(b.template_request, ['semantic_family', 'information_units', 'numeric_values', 'numeric_scale'],
    'template_request fields');
  const r = b.template_request;
  check(['bar_chart', 'numeric_comparison', 'data_summary'].includes(r.semantic_family), 'semantic_family mismatch');
  check(r.information_units === items.length && r.numeric_scale === 'linear', 'capacity/scale mismatch');
  check(JSON.stringify(r.numeric_values) === JSON.stringify(items.map(i => i.value)),
    'numeric_values differ from actual props');
  const positive = items.map(i => i.value).filter(v => v > 0);
  check(!positive.length || Math.max(...positive) / Math.min(...positive) < 50, 'would silently use log scale');
  for (const color of ['accent', 'background', 'foreground']) {
    check(/^#[0-9a-f]{6}$/i.test(b.props[color]), `${color} must be a six-digit hex color`);
  }
  // Conservative preflight, not a replacement for per-render font/layout review.
  const estimatedWidth = (s, px) => [...s].reduce((n, char) => n + (char.codePointAt(0) < 128 ? .7 : 1.1) * px, 0);
  const chartWidth = 1080 - 2 * Math.round(1080 * .08);
  check(estimatedWidth(title, Math.round(1920 * .058)) <= chartWidth, 'title too wide; choose/review a compatible layout');
  const slot = chartWidth / items.length - 12;
  // Continuous peak bounds the sampled spring in the frozen upstream source:
  // damping=14, mass=.7, stiffness=90. Its overshoot is ~0.28%, not 10%.
  const peak = 1 + Math.exp(-Math.PI * 14 / Math.sqrt(4 * .7 * 90 - 14 ** 2));
  for (const item of items) {
    check(estimatedWidth(item.label, Math.round(1920 * .028)) <= slot, 'label too wide for this template');
    const peakText = Math.round(item.value * peak).toLocaleString('en-US') + (unit ? ` ${unit}` : '');
    check(estimatedWidth(peakText, Math.round(1920 * .04)) <= slot, 'number/unit too wide for this template');
  }
  return b;
}

async function main(args) {
  if (args.length === 1 && args[0] === '--validate') {
    process.stdout.write(JSON.stringify(validateBrief(JSON.parse(fs.readFileSync(0, 'utf8')))));
    return;
  }
  const names = ['--brief', '--output', '--skill-root', '--runtime-root', '--browser', '--registry-path', '--registry-sha256', '--renderer-version'];
  if (args.length !== names.length * 2 || names.some((n, i) => args[i * 2] !== n)) {
    throw new Error('Use the approved data_rollup_adapter factory');
  }
  const opt = Object.fromEntries(names.map((n, i) => [n.slice(2), args[i * 2 + 1]]));
  const briefBytes = fs.readFileSync(opt.brief);
  const b = validateBrief(JSON.parse(briefBytes)); // Before bundler/browser imports.
  const root = opt['skill-root'];
  const registryPath = opt['registry-path'];
  if (!registryPath || path.posix.normalize(registryPath) !== registryPath || path.isAbsolute(registryPath) ||
      registryPath.split('/').some(part => !part || part === '.' || part === '..')) {
    throw new Error('Registry path must be a canonical relative POSIX path');
  }
  const resolvedRoot = fs.realpathSync(root);
  const resolvedRegistry = fs.realpathSync(path.join(resolvedRoot, registryPath));
  if (!resolvedRegistry.startsWith(`${resolvedRoot}${path.sep}`)) throw new Error('Registry path escapes the Skill');
  const registryBytes = fs.readFileSync(resolvedRegistry);
  if (sha(registryBytes) !== opt['registry-sha256']) throw new Error('Template registry changed; rebind');
  const template = JSON.parse(registryBytes).templates.find(t => t.template_id === TEMPLATE_ID);
  if (!template || template.render_contract.engine !== 'remotion') throw new Error('Template not registered for Remotion');
  const sourceDir = path.posix.dirname(template.source_entrypoint);
  const sources = template.source_files.map(s => {
    if (path.posix.dirname(s.path) !== sourceDir || s.path.split('/').includes('..') || path.isAbsolute(s.path)) {
      throw new Error('Unexpected template source path');
    }
    const bytes = fs.readFileSync(path.join(root, s.path));
    if (sha(bytes) !== s.sha256) throw new Error(`Template source changed: ${s.path}`);
    return {name: path.basename(s.path), bytes};
  });
  const runtime = createRequire(path.join(opt['runtime-root'], 'package.json'));
  for (const pkg of ['remotion', '@remotion/renderer', '@remotion/bundler']) {
    if (runtime(`${pkg}/package.json`).version !== opt['renderer-version']) throw new Error(`${pkg} version drift`);
  }
  fs.accessSync(opt.browser, fs.constants.X_OK);
  const {bundle} = runtime('@remotion/bundler');
  const {openBrowser, selectComposition, renderMedia} = runtime('@remotion/renderer');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hd-data-rollup-'));
  let browser;
  try {
    const src = path.join(temp, 'source');
    const publicDir = path.join(temp, 'public');
    fs.mkdirSync(src);
    fs.mkdirSync(publicDir);
    // Bundle the same bytes that passed the source hashes, not a later path read.
    for (const s of sources) fs.writeFileSync(path.join(src, s.name), s.bytes, {flag: 'wx'});
    const serveUrl = await bundle({
      entryPoint: path.join(src, 'entry.ts'), rootDir: opt['runtime-root'], publicDir,
      outDir: path.join(temp, 'bundle'), enableCaching: false,
      webpackOverride: config => ({...config, resolve: {...config.resolve,
        modules: [path.join(opt['runtime-root'], 'node_modules'), ...(config.resolve?.modules || ['node_modules'])]}}),
    });
    browser = await openBrowser('chrome', {browserExecutable: opt.browser, logLevel: 'error'});
    const inputProps = {...b.props, width: 1080, height: 1920};
    const composition = await selectComposition({serveUrl, id: 'DataRollup', inputProps,
      puppeteerInstance: browser, logLevel: 'error'});
    const rendered = path.join(temp, 'render.mp4');
    await renderMedia({serveUrl, inputProps, puppeteerInstance: browser,
      composition: {...composition, width: 1080, height: 1920, fps: 24,
        durationInFrames: b.canvas.duration_in_frames},
      codec: 'h264', pixelFormat: 'yuv420p', muted: true, concurrency: 1,
      imageFormat: 'png', colorSpace: 'bt709',
      // The bundled FFmpeg omits setsar; matching DAR to the native raster
      // writes square pixels without adding a filter or changing the geometry.
      ffmpegOverride: ({args}) => [...args.slice(0, -1), '-aspect', '9:16', args[args.length - 1]],
      disallowParallelEncoding: true, outputLocation: rendered, logLevel: 'error',
      offthreadVideoThreads: 1, offthreadVideoCacheSizeInBytes: 16 * 1024 * 1024,
      mediaCacheSizeInBytes: 16 * 1024 * 1024,
    });
    // ffmpeg children cannot inherit the executor's FD; Node publishes into it.
    await pipeline(fs.createReadStream(rendered), fs.createWriteStream(opt.output));
    process.stdout.write(JSON.stringify({template_id: TEMPLATE_ID, brief_sha256: sha(briefBytes),
      input_props_sha256: sha(JSON.stringify(inputProps)), frames: b.canvas.duration_in_frames,
      fps: 24, concurrency: 1, muted: true}));
  } finally {
    try { if (browser) await browser.close({silent: true}); }
    finally { fs.rmSync(temp, {recursive: true, force: true}); }
  }
}

module.exports = {validateBrief};
if (require.main === module || process.argv[1] === '-') main(process.argv.slice(2)).catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});

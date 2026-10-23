#!/usr/bin/env node
import {createRequire} from 'node:module';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {createReadStream, createWriteStream} from 'node:fs';
import {pipeline} from 'node:stream/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec = promisify(execFile);
const fail = (m) => { throw new Error(`[TALKCRAFT_AROLL_OVERLAY_INVALID] ${m}`); };
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const strictArgs = ['--brief', '--output', '--adapter-root', '--ffmpeg', '--source-sha256', '--browser'];
if (process.argv.length !== 14 || process.argv.slice(2).filter((x) => strictArgs.includes(x)).length !== 6) fail('usage: node render.mjs --brief /abs/brief.json --output /abs/out.mov --adapter-root /abs/aroll-overlay --ffmpeg /abs/ffmpeg --source-sha256 <64hex> --browser /abs/browser');
const value = (name) => { const i = process.argv.indexOf(name); return i < 0 ? null : process.argv[i + 1]; };
const briefPath = value('--brief'), outputPath = value('--output'), adapterRoot = value('--adapter-root'), ffmpeg = value('--ffmpeg'), sourceSha256 = value('--source-sha256'), browser = value('--browser');
if (![briefPath, outputPath, adapterRoot, ffmpeg, browser].every((v) => v && path.isAbsolute(v)) || !sourceSha256 || !/^[0-9a-f]{64}$/.test(sourceSha256)) fail('paths must be absolute and source-sha256 must be 64 lowercase hex');
const brief = JSON.parse(await readFile(briefPath, 'utf8'));
const input = brief?.renderer_input;
if (!brief || brief.schema_version !== 1 || !input || !brief.source_binding) fail('brief envelope is invalid');
const source = brief.source_binding;
if (typeof source.aroll_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(source.aroll_sha256) || typeof source.segment_id !== 'string' || !source.segment_id || !finite(source.start) || !finite(source.end) || source.start < 0 || source.end <= source.start) fail('source_binding is invalid');
if (![1, 2].includes(input.schema_version) || !input.canvas || Object.keys(input.canvas).sort().join(',') !== 'fps,frames,height,width' || input.canvas.width !== 1080 || input.canvas.height !== 1920 || input.canvas.fps !== 24) fail('canvas must be exactly 1080x1920 at 24fps');
if (!Number.isInteger(input.canvas.frames) || input.canvas.frames <= 0) fail('canvas.frames must be a positive integer');
const timing = input.timing;
const duration = input.canvas.frames / input.canvas.fps;
if (input.schema_version === 1) {
  if (!input.labels || Object.keys(input.labels).sort().join(',') !== 'fixed,moving' || ![input.labels.fixed, input.labels.moving].every((v) => typeof v === 'string' && /^[^\s\p{C}]{1,4}$/u.test(v))) fail('labels must be 1-4 visible single-line characters');
  const timingKeys = ['panel','plate','fixed_label','node','axis','shift','shift_duration','threshold','connector','moving_label','exit','exit_duration'];
  if (!timing || Object.keys(timing).sort().join(',') !== timingKeys.slice().sort().join(',') || timingKeys.some((k) => !finite(timing[k]) || timing[k] < 0 || timing[k] > duration) || timing.exit_duration <= 0 || timing.exit_duration > timing.exit || timing.exit > duration || timing.shift_duration <= 0 || timing.shift + timing.shift_duration > timing.exit + 1e-9 || timing.panel > timing.exit || timing.plate > timing.exit || timing.fixed_label > timing.exit || timing.node > timing.exit || timing.axis > timing.exit || timing.threshold > timing.exit || timing.connector > timing.exit || timing.moving_label > timing.exit) fail('timing must be finite, positive where required, and fit before exit');
} else {
  if (!['flow', 'contrast'].includes(input.mode) || !Array.isArray(input.labels) || input.labels.length !== (input.mode === 'flow' ? 3 : 2) || !input.labels.every((v) => typeof v === 'string' && /^[^\s\p{C}]{1,4}$/u.test(v))) fail('relation labels or mode are invalid');
  const legacyKeys = ['panel','first','step','exit','exit_duration'];
  const anchoredKeys = ['panel','label_times','exit','exit_duration'];
  const keys = Object.keys(timing ?? {}).sort().join(',');
  const legacy = keys === legacyKeys.slice().sort().join(',');
  const anchored = keys === anchoredKeys.slice().sort().join(',');
  const labelTimes = legacy ? input.labels.map((_, i) => timing.first + i * timing.step) : timing?.label_times;
  if (!timing || (!legacy && !anchored) || !finite(timing.panel) || !finite(timing.exit) || !finite(timing.exit_duration) || timing.panel < 0 || timing.exit_duration <= 0 || timing.exit_duration > timing.exit || timing.exit > duration || !Array.isArray(labelTimes) || labelTimes.length !== input.labels.length || labelTimes.some((v, i) => !finite(v) || v < 0 || v > duration || (i > 0 && v <= labelTimes[i - 1])) || labelTimes.at(-1) + 0.25 > timing.exit) fail('relation timing is invalid');
}
const runtime = path.resolve(adapterRoot, '../runtime');
const projectRoot = path.resolve(adapterRoot, '../../../../../');
const sourceFiles = [
  ...['entry.tsx', 'types.ts', 'render.mjs'].map((name) => path.join(adapterRoot, name)),
  ...['package.json', 'package-lock.json'].map((name) => path.join(adapterRoot, name)),
  path.join(adapterRoot, '../upstream/template/motion-systems/schematic.tsx'),
  path.join(adapterRoot, '../upstream/template/motion-systems/icons.ts'),
  path.join(runtime, 'package.json'),
  path.join(runtime, 'package-lock.json'),
];
const sourceClosureHash = async () => {
  const entries = [];
  for (const file of sourceFiles) {
  const relative = path.relative(projectRoot, file).split(path.sep).join('/');
  entries.push([relative, crypto.createHash('sha256').update(await readFile(file)).digest('hex')]);
  }
  entries.sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return crypto.createHash('sha256').update(JSON.stringify(Object.fromEntries(entries)) + '\n', 'utf8').digest('hex');
};
const checkSourceClosure = async () => {
  const actual = await sourceClosureHash();
  if (actual !== sourceSha256) fail(`source closure hash mismatch: expected ${sourceSha256}, actual ${actual}`);
};
await checkSourceClosure();
const require = createRequire(path.join(runtime, 'package.json'));
const {bundle} = require('@remotion/bundler');
const {renderMedia, selectComposition} = require('@remotion/renderer');
const tmp = await mkdtemp(path.join(os.tmpdir(), 'talkcraft-aroll-overlay-'));
const webm = path.join(tmp, 'overlay.webm');
const mov = path.join(tmp, 'overlay.mov');
try {
  const serveUrl = await bundle({entryPoint: path.join(adapterRoot, 'entry.tsx'), rootDir: adapterRoot, webpackOverride: (config) => ({...config, resolve: {...config.resolve, modules: [path.join(adapterRoot, 'node_modules'), path.join(runtime, 'node_modules'), ...(config.resolve?.modules ?? [])]}}), onProgress: () => {}});
  await checkSourceClosure();
  const composition = await selectComposition({serveUrl, id: 'ArollOverlay', inputProps: input, browserExecutable: browser});
  await renderMedia({composition, serveUrl, inputProps: input, outputLocation: webm, codec: 'vp9', pixelFormat: 'yuva420p', imageFormat: 'png', muted: true, concurrency: 1, browserExecutable: browser});
  await exec(ffmpeg, ['-y', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', webm, '-an', '-c:v', 'qtrle', '-pix_fmt', 'argb', '-f', 'mov', mov]);
  await checkSourceClosure();
  // The executor owns outputPath (often /dev/fd/N). Nested ffmpeg does not
  // inherit that descriptor; copy in this process after successful encoding.
  await pipeline(createReadStream(mov), createWriteStream(outputPath));
} finally { await rm(tmp, {recursive: true, force: true}); }

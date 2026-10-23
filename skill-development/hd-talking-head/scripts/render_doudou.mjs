#!/usr/bin/env node
// Render a Job-owned Remotion entry which imports pinned Doudou components.
// This bridge supplies execution only, not a new visual template or engine.
import {createRequire} from 'node:module';
import {readFile, realpath, mkdtemp, writeFile, rm, mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

const args = process.argv.slice(2);
const frozenMode = args[0] === '--brief';
const names = frozenMode ? ['--brief', '--media-manifest', '--project-root', '--output'] :
  ['--project-root', '--entry', '--composition', '--output'];
if (args.length !== 8 || names.some((name, i) => args[i * 2] !== name)) {
  throw new Error('Usage: --project-root /project --entry /entry.tsx --composition ID --output /video.mp4');
}
const opts = Object.fromEntries(names.map((name, i) => [name, args[i * 2 + 1]]));
const project = opts['--project-root'];
const output = opts['--output'];
if (![project, output].every(path.isAbsolute)) throw new Error('Paths must be absolute');
const root = await realpath(project);
const sha = data => createHash('sha256').update(data).digest('hex');
let entry = opts['--entry'];
let compositionId = opts['--composition'];
let expectedFrames;
let temporary;
try {
if (frozenMode) {
  const payload = await readFile(opts['--brief']);
  const brief = JSON.parse(payload);
  const manifest = JSON.parse(await readFile(opts['--media-manifest'], 'utf8'));
  if (brief.schema_version !== 2 || brief.composition.width !== 1080 ||
      brief.composition.height !== 1920 || brief.composition.fps !== 24 ||
      !Number.isInteger(brief.composition.frames) || brief.composition.frames < 1 ||
      manifest.schema_version !== 'reference-process-media/v1' ||
      manifest.brief_sha256 !== sha(payload) || manifest.media.length !== 2) {
    throw new Error('Doudou frozen brief/clock mismatch');
  }
  const records = Object.fromEntries(manifest.media.map(record => [record.media_ref, record]));
  if (new Set(manifest.media.map(record => record.media_ref)).size !== 2 ||
      !records.entry || !records.hand ||
      ![records.entry, records.hand].every(record => Number.isInteger(record.fd) && record.fd >= 0 &&
        typeof record.sha256 === 'string' && record.sha256.length === 64)) {
    throw new Error('Frozen Doudou entry and hand required');
  }
  const data = await readFile(`/dev/fd/${records.entry.fd}`);
  const handData = await readFile(`/dev/fd/${records.hand.fd}`);
  if (sha(data) !== brief.entry.sha256 || sha(data) !== records.entry.sha256 || data.length !== records.entry.byte_length ||
      sha(handData) !== brief.hand.sha256 || sha(handData) !== records.hand.sha256 || handData.length !== records.hand.byte_length) {
    throw new Error('Doudou entry or hand identity changed');
  }
  if (handData.length < 26 || handData.readUInt32BE(0) !== 0x89504e47 || handData.readUInt32BE(4) !== 0x0d0a1a0a ||
      handData.toString('ascii', 12, 16) !== 'IHDR' || handData.readUInt32BE(16) !== brief.hand.width ||
      handData.readUInt32BE(20) !== brief.hand.height || handData[25] !== 6 ||
      !Number.isFinite(brief.hand.tip_x) || !Number.isFinite(brief.hand.tip_y) ||
      brief.hand.tip_x < 0 || brief.hand.tip_x >= brief.hand.width || brief.hand.tip_y < 0 || brief.hand.tip_y >= brief.hand.height) {
    throw new Error('Doudou hand must be the declared RGBA PNG');
  }
  const text = data.toString('utf8');
  // This route accepts reviewed, self-contained scene code only, not live assets.
  if (!text.includes('doudou-remotion-whiteboard') ||
      /(?:from\s*|import\s*\(|require\s*\()\s*['"](?:\.|\/|https?:)/.test(text) ||
      /https?:\/\/|\bfetch\s*\(|\bAudio\b|data:[^'"`]+|staticFile\s*\((?!['"]hand\.png['"]\s*\))/.test(text) ||
      (text.match(/staticFile\s*\(/g) || []).length !== 1 || !/RealHandFollower/.test(text) ||
      !/staticFile\s*\(['"]hand\.png['"]\s*\)/.test(text)) {
    throw new Error('Doudou entry must be self-contained and silent');
  }
  temporary = await mkdtemp(path.join(root, 'edit/hd/.doudou-render-'));
  await mkdir(path.join(temporary, 'public'), {recursive: true});
  await writeFile(path.join(temporary, 'public/hand.png'), handData, {flag: 'wx'});
  entry = path.join(temporary, 'entry.tsx');
  await writeFile(entry, data, {flag: 'wx'});
  compositionId = brief.composition.id;
  expectedFrames = brief.composition.frames;
}
const source = path.join(root, 'skill-development/vendor/doudou-remotion-whiteboard');
const commit = execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (commit !== 'd41f61c889c315b2a590fee61db3a62cf003adc9' ||
    execFileSync('git', ['-C', source, 'status', '--porcelain'], {encoding: 'utf8'}).trim()) {
  throw new Error('Doudou source identity changed');
}
const entryPath = await realpath(entry);
const relative = path.relative(root, entryPath);
if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Entry must belong to this project');
if (!(await readFile(entryPath, 'utf8')).includes('doudou-remotion-whiteboard')) {
  throw new Error('Entry must import the upstream Doudou source');
}
const runtime = path.join(root, 'edit/hd/integrations/talkcraft/runtime');
// The shared executor deliberately starts outside the project; never let
// Remotion infer a browser cache from that working directory or download one.
const browserExecutable = await realpath(path.join(root,
  '.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell'));
const require = createRequire(path.join(runtime, 'package.json'));
const {bundle} = require('@remotion/bundler');
const {renderMedia, selectComposition} = require('@remotion/renderer');
if (require('@remotion/renderer/package.json').version !== '4.0.520') {
  throw new Error('Doudou requires the qualified Remotion 4.0.520 runtime');
}
const serveUrl = await bundle({entryPoint: entryPath, rootDir: root, publicDir: frozenMode ? path.join(temporary, 'public') : undefined,
  webpackOverride: config => ({...config, resolve: {...config.resolve,
    alias: {...config.resolve?.alias, 'doudou-remotion-whiteboard': source},
    modules: [path.join(runtime, 'node_modules'), ...(config.resolve?.modules ?? [])]}})});
const composition = await selectComposition({serveUrl, id: compositionId, browserExecutable});
if (composition.width !== 1080 || composition.height !== 1920 || composition.fps !== 24 ||
    (expectedFrames !== undefined && composition.durationInFrames !== expectedFrames)) {
  throw new Error('Composition must be native 1080x1920 at 24fps');
}
// Remotion validates a real filename extension; the executor owns a frozen
// output descriptor. Render locally, then copy bytes into that same descriptor.
const renderOutput = frozenMode ? path.join(temporary, 'render.mp4') : output;
await renderMedia({serveUrl, composition, browserExecutable, outputLocation: renderOutput,
  codec: 'h264', pixelFormat: 'yuv420p', imageFormat: 'png', colorSpace: 'bt709',
  ffmpegOverride: ({type, args}) => type === 'stitcher'
    ? [...args.slice(0, -1), '-bsf:v', 'h264_metadata=sample_aspect_ratio=1/1', args.at(-1)] : args,
  muted: true, concurrency: 1});
if (frozenMode) await writeFile(output, await readFile(renderOutput));
console.log(JSON.stringify({status: 'rendered', upstream_commit: commit,
  entry: entryPath, composition: compositionId, output,
  width: composition.width, height: composition.height, fps: composition.fps,
  frames: composition.durationInFrames, frozen_entry: frozenMode, external_requests: 0}));
} finally {
  if (temporary) await rm(temporary, {recursive: true});
}

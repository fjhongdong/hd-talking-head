#!/usr/bin/env node
// Render one frozen callout composition to transparent QTRLE MOV.
'use strict';
const {spawnSync} = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
function arg(name) { const i = process.argv.indexOf(name); if (i < 0 || !process.argv[i + 1]) throw new Error(`Missing ${name}`); return process.argv[i + 1]; }
function sha256(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function run(command, args, options = {}) { const r = spawnSync(command, args, {stdio: 'pipe', encoding: 'utf8', ...options}); if (r.error) throw r.error; return r; }
function fail(message, dir) { if (dir) { try { fs.writeFileSync(path.join(dir, 'failure.log'), `${message}\n`); } catch (_) {} console.error(`${message}\nPrivate diagnostics: ${dir}`); } else console.error(message); process.exitCode = 1; }
function probe(file) {
  const r = run(ffprobe, ['-v', 'error', '-show_entries', 'stream=codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames,duration,pix_fmt:format=duration', '-of', 'json', file]);
  if (r.status !== 0) throw new Error(`ffprobe failed: ${r.stderr}`);
  const data = JSON.parse(r.stdout); const streams = data.streams || [];
  if (streams.length !== 1 || streams[0].codec_type !== 'video') throw new Error('expected exactly one video stream');
  const s = streams[0]; return {s, fps: String(s.r_frame_rate || s.avg_frame_rate || ''), frames: Number(s.nb_frames), duration: Number(s.duration ?? data.format?.duration), data};
}
function assertNative(file, expected) {
  const p = probe(file); const s = p.s;
  if (s.width !== expected.width || s.height !== expected.height) throw new Error(`dimensions ${s.width}x${s.height}`);
  if (p.fps !== '24/1') throw new Error(`fps ${p.fps}`);
  if (p.frames !== expected.frames) throw new Error(`frames ${p.frames}, expected ${expected.frames}`);
  if (!Number.isFinite(p.duration) || Math.abs(p.duration - expected.frames / 24) > 0.0005) throw new Error(`duration ${p.duration}`);
  if (!/^(yuva|argb|rgba|abgr)/.test(String(s.pix_fmt))) throw new Error(`pix_fmt lacks alpha: ${s.pix_fmt}`);
  return p;
}
function alphaRange(file, frame) {
  const r = run(ffmpeg, ['-v', 'error', '-i', file, '-vf', `select=eq(n\\,${frame})`, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'], {maxBuffer: 32 * 1024 * 1024, encoding: null});
  if (r.status !== 0) throw new Error(`RGBA decode failed: ${r.stderr}`);
  const bytes = Buffer.from(r.stdout); if (bytes.length !== 1080 * 1920 * 4) throw new Error(`RGBA bytes ${bytes.length}`);
  let min = 255, max = 0; for (let i = 3; i < bytes.length; i += 4) { if (bytes[i] < min) min = bytes[i]; if (bytes[i] > max) max = bytes[i]; }
  if (min !== 0 || max === 0) throw new Error(`alpha range ${min}-${max}`); return {min, max, bytes: bytes.length, frame};
}
const skillRoot = arg('--skill-root');
const projectRoot = arg('--project-root'); const briefPath = arg('--brief'); const outputPath = arg('--output'); const manifestPath = arg('--media-manifest');
const ffmpeg = arg('--ffmpeg'), ffprobe = arg('--ffprobe');
let privateDir;
try {
  const briefBytes = fs.readFileSync(briefPath); const brief = JSON.parse(briefBytes); const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (manifest.schema_version !== 'reference-process-media/v1' || !Array.isArray(manifest.media) || manifest.media.length !== 1) throw new Error('reference-process-media/v1 with one native-entry is required');
  const record = manifest.media[0]; if (record.media_ref !== 'native-entry' || !Number.isInteger(record.fd) || record.fd < 0) throw new Error('manifest native-entry fd is invalid');
  const entry = brief.entry || {}, composition = brief.composition || {};
  const expected = {width: 1080, height: 1920, fps: 24, frames: composition.frames};
  if (brief.template_request?.semantic_family !== 'callout_pin'
      || composition.width !== 1080 || composition.height !== 1920 || composition.fps !== 24
      || composition.alpha !== true || !Number.isInteger(expected.frames) || expected.frames <= 0
      || Math.abs((brief.source_binding.end - brief.source_binding.start) * 24 - expected.frames) > 1e-6)
    throw new Error('only the approved callout_pin portrait clock is accepted');
  const entryBytes = fs.readFileSync(`/dev/fd/${record.fd}`);
  if (manifest.brief_sha256 !== sha256(briefBytes)) throw new Error('brief_sha256 mismatch');
  if (record.sha256 !== entry.sha256 || record.sha256 !== sha256(entryBytes)) throw new Error('native-entry sha256 mismatch');
  if (record.byte_length !== entryBytes.length) throw new Error('native-entry byte_length mismatch');
  privateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hd-motion-graphics-')); const compositions = path.join(privateDir, 'compositions'); fs.mkdirSync(compositions);
  fs.writeFileSync(path.join(compositions, 'index.html'), entryBytes); fs.writeFileSync(path.join(privateDir, 'hyperframes.json'), JSON.stringify({paths: {blocks: 'compositions'}}));
  const nativePath = path.join(privateDir, 'native.mov'); const cli = path.join(projectRoot, 'skill-development/runtime/hyperframes-0.8.167/node_modules/hyperframes/bin/hyperframes.mjs');
  const render = run(process.execPath, [cli, 'render', privateDir, '--composition', 'compositions/index.html', '--output', nativePath, '--format', 'mov', '--fps', '24', '--workers', '1', '--quality', 'delivery', '--low-memory-mode', '--no-browser-gpu', '--no-best-effort', '--quiet'], {cwd: privateDir, timeout: 240000, env: {...process.env, HYPERFRAMES_BROWSER_PATH: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1'}});
  if (render.status !== 0 || !fs.existsSync(nativePath)) throw new Error(`HyperFrames render failed: ${render.stderr}`);
  const nativeProbe = assertNative(nativePath, expected); const nativeAlpha = alphaRange(nativePath, Math.floor(expected.frames / 2));
  const converted = path.join(privateDir, 'converted.mov'); const conv = run(ffmpeg, ['-y', '-v', 'error', '-i', nativePath, '-an', '-vf', 'setsar=1/1', '-r', '24', '-c:v', 'qtrle', '-pix_fmt', 'argb', converted]);
  if (conv.status !== 0) throw new Error(`QTRLE conversion failed: ${conv.stderr}`);
  const finalProbe = assertNative(converted, expected); const finalAlpha = alphaRange(converted, Math.floor(expected.frames / 2)); fs.writeFileSync(outputPath, fs.readFileSync(converted));
  console.log(JSON.stringify({status: 'ok', output: outputPath, renderer: 'hyperframes', native: {frames: nativeProbe.frames, fps: nativeProbe.fps, pix_fmt: nativeProbe.s.pix_fmt, alpha: nativeAlpha}, outputProbe: {frames: finalProbe.frames, fps: finalProbe.fps, pix_fmt: finalProbe.s.pix_fmt, alpha: finalAlpha}, skillRoot}));
  fs.rmSync(privateDir, {recursive: true, force: true});
} catch (error) { fail(error.stack || String(error), privateDir); }

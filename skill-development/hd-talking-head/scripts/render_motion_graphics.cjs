#!/usr/bin/env node
// Render one job-authored motion graphic (hyperframes/1 HTML) to a transparent QTRLE MOV.
'use strict';

const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Error('Missing ' + name);
  return process.argv[i + 1];
}

const skillRoot = arg('--skill-root');
const projectRoot = arg('--project-root');
const briefPath = arg('--brief');
const outputPath = arg('--output');

const brief = JSON.parse(fs.readFileSync(briefPath, 'utf8'));
// brief 位于 <job>/native-inputs/… 下;从 brief 路径反推 Job 根
const briefDir = path.dirname(path.resolve(briefPath));
const niIdx = briefDir.split(path.sep).lastIndexOf('native-inputs');
const jobDir = niIdx > 0
  ? briefDir.split(path.sep).slice(0, niIdx).join(path.sep)
  : path.resolve(briefDir, '..');
const entryPath = path.resolve(jobDir, brief.entry.job_path);

// Stage: copy the entry HTML into a temporary composition directory
const compositionDir = path.join(path.dirname(outputPath), '.mg-composition');
fs.mkdirSync(compositionDir, {recursive: true});
fs.copyFileSync(entryPath, path.join(compositionDir, 'index.html'));

// Render via the project hyperframes CLI (same pattern as local_canonical_renderer)
const cli = path.join(projectRoot,
  'skill-development/runtime/hyperframes-0.8.167/node_modules/hyperframes/bin/hyperframes.mjs');
const tmpOutput = path.join(compositionDir, 'render.mov');

const result = spawnSync(process.execPath, [
  cli, 'render', compositionDir, '--output', tmpOutput,
], {stdio: 'pipe', timeout: 240000, cwd: compositionDir});

if (result.status !== 0) {
  console.error('Motion graphics render failed:', result.stderr?.toString().slice(-3000));
  process.exit(1);
}

// Convert to QTRLE with alpha if the source has it; otherwise copy
const ffmpeg = 'ffmpeg';
const probe = spawnSync('ffprobe', [
  '-v', 'error', '-select_streams', 'v:0', '-show_entries',
  'stream=pix_fmt', '-of', 'json', tmpOutput,
], {stdio: 'pipe'});
const hasAlpha = probe.status === 0 &&
  JSON.parse(probe.stdout.toString()).streams?.[0]?.pix_fmt?.includes('alpha');

if (hasAlpha) {
  const conv = spawnSync(ffmpeg, [
    '-y', '-i', tmpOutput, '-c:v', 'qtrle', '-pix_fmt', 'argb', outputPath,
  ], {stdio: 'pipe'});
  if (conv.status !== 0) {
    console.error('QTRLE conversion failed:', conv.stderr?.toString().slice(-2000));
    process.exit(1);
  }
} else {
  fs.copyFileSync(tmpOutput, outputPath);
}

fs.rmSync(compositionDir, {recursive: true, force: true});
console.log(JSON.stringify({status: 'ok', output: outputPath}));

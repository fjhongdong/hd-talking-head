// Runtime helpers (springs, seeded random) and `om qa` on synthetic videos.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { qa } from '../cli/lib/qa.js';

globalThis.window = {};
globalThis.document = { querySelector: () => null };
createRequire(import.meta.url)('../runtime/om.js');
const OM = window.OM;

test('OM.spring starts at 0, ends exactly at 1, and overshoots by about the bounce', () => {
  for (const b of [0, 0.05, 0.1, 0.25]) {
    const e = OM.spring(b);
    assert.equal(e(0), 0);
    assert.equal(e(1), 1);
    let peak = 0;
    for (let p = 0; p <= 1; p += 0.001) peak = Math.max(peak, e(p));
    assert.ok(Math.abs(peak - 1 - b) < 0.01, `bounce ${b}: peak ${peak}`);
    assert.ok(Math.abs(e(0.98) - 1) < 0.01, 'settled near the end');
  }
});

test('OM.springValue is a pure function of time that follows every target', () => {
  const ch = [{ at: 1, to: 100 }, { at: 2, to: 40 }];
  assert.equal(OM.springValue(0, ch, 0.5), 0);
  assert.ok(Math.abs(OM.springValue(0, ch, 1.9, { settle: 0.5 }) - 100) < 1);
  assert.ok(Math.abs(OM.springValue(0, ch, 3, { settle: 0.5 }) - 40) < 0.5);
  assert.equal(OM.springValue(0, ch, 1.4), OM.springValue(0, ch, 1.4));
});

test('OM.random is deterministic per seed', () => {
  const a = OM.random(7), b = OM.random(7), c = OM.random(8);
  const xa = [a(), a(), a()], xb = [b(), b(), b()];
  assert.deepEqual(xa, xb);
  assert.notDeepEqual(xa, [c(), c(), c()]);
  assert.ok(xa.every((x) => x >= 0 && x < 1));
});

const ff = (args) => assert.equal(spawnSync('ffmpeg', ['-v', 'error', '-y', ...args]).status, 0);
const has = spawnSync('ffmpeg', ['-version']).status === 0;

test('om qa finds a single-frame pop, a hard cut and dead time', { skip: !has && 'no ffmpeg' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'om-qa-'));
  // a moving bar, 1 frame of white at 1.0 s, a cut to a different scene at 2 s, then 1.5 s frozen.
  ff(['-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=30:d=4.5', '-f', 'lavfi', '-i', 'color=c=white:s=40x60:r=30:d=4.5', '-filter_complex',
    "[0][1]overlay=x='mod(t*120,320)':y=60:eval=frame:enable='lt(t,2)',drawbox=x=0:y=0:w=320:h=180:c=white:t=fill:enable='between(n,30,30)',drawbox=x=40:y=20:w=240:h=140:c=red:t=fill:enable='gte(t,2)'",
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', join(dir, 'a.mp4')]);
  const r = qa(join(dir, 'a.mp4'));
  assert.ok(r.pops.some((p) => Math.abs(p.at - 1) < 0.05), JSON.stringify(r.pops));
  assert.ok(r.cuts.some((c) => Math.abs(c - 2) < 0.05), JSON.stringify(r.cuts));
  assert.ok(r.dead.some((d) => d.from >= 1.9 && d.seconds >= 2), JSON.stringify(r.dead));
});

test('om qa loop check: a cycle matches, a one-way move does not', { skip: !has && 'no ffmpeg' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'om-qa-'));
  // overlay re-evaluates x every frame (drawbox does not)
  const moving = (x, out) => ff(['-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=30:d=2', '-f', 'lavfi', '-i', 'color=c=white:s=40x60:r=30:d=2',
    '-filter_complex', `[0][1]overlay=x='${x}':y=60:eval=frame`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', join(dir, out)]);
  moving('140+100*sin(2*PI*t*30/59)', 'loop.mp4');
  moving('t*120', 'oneway.mp4');
  assert.equal(qa(join(dir, 'loop.mp4'), { loop: true }).loop.seamless, true);
  assert.equal(qa(join(dir, 'oneway.mp4'), { loop: true }).loop.seamless, false);
});

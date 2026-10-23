import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { findChrome } from '../cli/lib/browser.js';
import { capture } from '../cli/lib/capture.js';
import { HAS_FFMPEG, makeFilm } from './fixture-film.js';

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const skip = (!findChrome() && 'no Chrome') || (!HAS_FFMPEG && 'no ffmpeg');
const size = (png) => ({ w: png.readUInt32BE(16), h: png.readUInt32BE(20) });

test('capture: a page that is not a composition is photographed as it is', { skip }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'om-cap-'));
  writeFileSync(join(dir, 'p.html'), '<!doctype html><body style="margin:0;background:#f00"><p>no timeline here</p></body>');
  const { shots, info } = await capture(join(dir, 'p.html'), { lenient: true, size: [400, 300] });
  assert.deepEqual(size(shots[0].png), { w: 400, h: 300 });
  assert.equal(info.timelines.length, 0);
});

test('capture: times seek the timeline, a clip crops (and scales) a close-up, html overrides the file', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false });
  const { shots } = await capture(index, { times: [0, 1.5], clip: { x: 0, y: 100, width: 100, height: 50, scale: 2 } });
  assert.equal(shots.length, 2);
  assert.deepEqual(size(shots[0].png), { w: 200, h: 100 });
  assert.notDeepEqual(shots[0].png, shots[1].png, 'the square moved between 0 and 1.5 s');
  const html = '<!doctype html><html><head></head><body style="margin:0"><div data-composition-id="x" data-width="200" data-height="100" style="width:200px;height:100px;background:#0f0"></div><script>window.__timelines={x:{seek(){},pause(){},duration:()=>1,labels:{}}}</script></body></html>';
  const o = await capture(index, { html });
  assert.deepEqual(size(o.shots[0].png), { w: 200, h: 100 }, 'the text given is what is shown, at its own size');
});

test('om look --at: the same path as the render, a full frame and a close-up of a clicked spot', { skip }, () => {
  const { dir } = makeFilm({ video: false, sound: false });
  const r = spawnSync('node', [join(PKG, 'cli', 'om.js'), 'look', dir, '--at', '1'], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const look = join(dir, '.om', 'look');
  const sub = join(look, readdirSync(look)[0]);
  assert.deepEqual(size(spawnSync('cat', [join(sub, 'frame.png')], { encoding: 'buffer' }).stdout), { w: 320, h: 180 });
  assert.match(r.stdout, /frame\.png/);
});

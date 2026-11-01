import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { findChrome } from '../cli/lib/sound.js';
import { still } from '../cli/lib/still.js';

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('om still: a PNG of a page at the frame size, and at given times of its timeline', { skip: !findChrome() && 'no Chrome' }, async () => {
  const dir = join(mkdtempSync(join(tmpdir(), 'om-still-')), '方向');
  mkdirSync(dir, { recursive: true });
  cpSync(join(PKG, 'templates', 'blank', 'vendor', 'gsap.min.js'), join(dir, 'gsap.min.js'));
  writeFileSync(join(dir, 'a.html'), '<!doctype html><html><head><script src="gsap.min.js"></script></head><body style="margin:0"><div data-composition-id="k" data-width="640" data-height="360" style="width:640px;height:360px;background:#000"><i id="x" style="position:absolute;left:0;top:0;width:40px;height:40px;background:#fff"></i></div><script>window.__timelines={};const tl=gsap.timeline({paused:true});tl.to("#x",{x:600,duration:2});window.__timelines.k=tl;</script></body></html>');
  const out = await still(join(dir, 'a.html'), { at: '0,2' });
  assert.match(out, /a-0\.00s\.png[\s\S]*a-2\.00s\.png/);
  assert.match(out, /640×360/);
  // the white square sits at the left at 0 s and at the right at 2 s: compare the brightness of the two edges
  const bright = (f, x) => Number(spawnSync('ffmpeg', ['-v', 'error', '-i', f, '-vf', `crop=40:40:${x}:0,scale=1:1,format=gray`, '-f', 'rawvideo', '-'], { encoding: 'buffer' }).stdout[0]);
  assert.ok(bright(join(dir, 'a-0.00s.png'), 0) > 200 && bright(join(dir, 'a-0.00s.png'), 600) < 50, 'at 0 s the square is on the left');
  assert.ok(bright(join(dir, 'a-2.00s.png'), 600) > 200, 'at 2 s it has moved right');
});

test('om new: fills a folder that has research in it, refuses one that already holds a film', () => {
  const dir = join(mkdtempSync(join(tmpdir(), 'om-new-')), 'film');
  mkdirSync(join(dir, 'research'), { recursive: true });
  writeFileSync(join(dir, 'research', 'notes.md'), 'keep me');
  const r = spawnSync('node', [join(PKG, 'cli', 'om.js'), 'new', dir], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(existsSync(join(dir, 'index.html')));
  assert.equal(readFileSync(join(dir, 'research', 'notes.md'), 'utf8'), 'keep me');
  const again = spawnSync('node', [join(PKG, 'cli', 'om.js'), 'new', dir], { encoding: 'utf8' });
  assert.notEqual(again.status, 0);
  assert.match(again.stderr + again.stdout, /already has an index\.html/);
});

test('om swatch: palette lines become one PNG; contrast and the shared house look are reported', { skip: !findChrome() && 'no Chrome' }, async () => {
  const { parsePalettes, swatch } = await import('../cli/lib/swatch.js');
  const dir = mkdtempSync(join(tmpdir(), 'om-swatch-'));
  const card = (k, n, g, a) => `${k} · ${n}       language: x   look: y\nPalette:  ground ${g} 70 · ink #F2EADB · accent ${a} 5 — from: README\n`;
  writeFileSync(join(dir, 'directions.md'), card('A', '终端', '#100E0C', '#C95434') + card('B', '镜子', '#0C0807', '#E8A33D') + card('C', '咒语', '#0D0B0A', '#E8452C'));
  const ps = parsePalettes(readFileSync(join(dir, 'directions.md'), 'utf8'));
  assert.deepEqual(ps.map((p) => p.name), ['A · 终端', 'B · 镜子', 'C · 咒语']);
  assert.deepEqual(ps[0].swatches.map((s) => [s.role, s.share]), [['ground', 70], ['ink', null], ['accent', 5]]);
  const out = await swatch(join(dir, 'directions.md'));
  assert.ok(existsSync(join(dir, 'directions-palettes.png')));
  assert.match(out, /every direction has a dark ground/);
  assert.match(out, /every accent is a warm orange-red/);
  assert.match(out, /ink \d+\.\d:1/);
});

test('om still: a page that registers window.__timelines itself (as the templates do) is still sought', { skip: !findChrome() && 'no Chrome' }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'om-still-shim-'));
  cpSync(join(PKG, 'templates', 'blank', 'vendor', 'gsap.min.js'), join(dir, 'gsap.min.js'));
  writeFileSync(join(dir, 'p.html'), '<!doctype html><html data-composition-variables=\'[{"id":"w","type":"number","default":40}]\'><head><script src="gsap.min.js"></script></head><body style="margin:0"><div data-composition-id="k" data-width="640" data-height="360" style="width:640px;height:360px;background:#000"><i id="x" style="position:absolute;left:0;top:0;height:40px;background:#fff"></i></div><script>const V=window.__hyperframes.getVariables();document.getElementById("x").style.width=V.w+"px";const tl=gsap.timeline({paused:true});tl.to("#x",{x:600,duration:2});window.__timelines["k"]=tl;</script></body></html>');
  await still(join(dir, 'p.html'), { at: '2' });
  const bright = (f, x) => Number(spawnSync('ffmpeg', ['-v', 'error', '-i', f, '-vf', `crop=40:40:${x}:0,scale=1:1,format=gray`, '-f', 'rawvideo', '-'], { encoding: 'buffer' }).stdout[0]);
  assert.ok(bright(join(dir, 'p-2.00s.png'), 600) > 200, 'at 2 s the square has moved right (the timeline was found and sought)');
});

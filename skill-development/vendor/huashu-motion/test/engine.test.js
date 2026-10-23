import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { findChrome } from '../cli/lib/browser.js';
import { openFilm } from '../cli/lib/capture.js';
import { HAS_FFMPEG, makeFilm } from './fixture-film.js';

const skip = (!findChrome() && 'no Chrome') || (!HAS_FFMPEG && 'no ffmpeg');

test('engine: variables come typed, overrides apply, data-var-text is bound, the start-up handshake passes', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false });
  const film = await openFilm(index, { variables: { title: '你好', n: '7', on: 'true' } });
  try {
    assert.equal(film.info.duration, 2);
    assert.equal(film.info.width, 320);
    assert.deepEqual(film.info.labels, { 'scene:a': 0 });
    // the same object the compositions read through window.__hyperframes.getVariables (compat) comes back typed as declared
    assert.deepEqual(await film.evaluate('window.__hyperframes.getVariables()'), { title: '你好', n: 7, on: true });
    assert.equal(await film.evaluate('document.getElementById("t").textContent'), '你好');
    // each variable is also a CSS custom property (var(--title)) — compositions draw their colours with it
    assert.equal(await film.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--n").trim()'), '7');
    assert.deepEqual(film.errors, [], 'the non-JS <script type="text/vnd.abc"> is not parsed as JavaScript');
  } finally { await film.close(); }
});

test('engine: defaults when nothing overrides; seek drives the timeline and waits for the page', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false });
  const film = await openFilm(index, {});
  try {
    assert.equal(await film.evaluate('document.getElementById("t").textContent'), 'Hello');
    await film.seek(1.5);
    assert.equal(await film.evaluate('window.__lastSeek'), 1.5);
    assert.equal(await film.evaluate('document.getElementById("box").style.transform'), 'translateX(150px)');
  } finally { await film.close(); }
});

test('engine: a video without an id gets one, is hidden outside its window and shows its frame inside it', { skip }, async () => {
  const { index } = makeFilm({});
  const film = await openFilm(index, {});
  try {
    const [v] = (await film.media()).filter((m) => m.tag === 'video');
    assert.match(v.id, /^om-media-\d+$/);
    assert.equal(v.start, 0.5);
    assert.equal(v.duration, 1);
    // frames are only ever drawn from a table the renderer provides: asking for one that is missing is an error
    await film.seek(0.2); // outside the window: nothing needed
    assert.equal(await film.evaluate('document.querySelector("video").style.visibility'), 'hidden');
    await assert.rejects(() => film.seek(1), /no extracted frames/);
  } finally { await film.close(); }
});

test('engine: window.__hf.buildReady and OM.ready are awaited before the first frame', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false, script: 'window.__hf = window.__hf || {}; window.__hf.buildReady = window.__hf.buildReady || {}; window.__hf.buildReady.x = new Promise((ok) => setTimeout(() => { window.__late = 1; ok(); }, 400)); OM.ready(new Promise((ok) => setTimeout(() => { window.__late2 = 1; ok(); }, 600)));' });
  const film = await openFilm(index, {});
  try {
    assert.equal(await film.evaluate('window.__late'), 1);
    assert.equal(await film.evaluate('window.__late2'), 1);
  } finally { await film.close(); }
});

test('engine: a composition that never becomes ready fails the start, with the reason', { skip }, async () => {
  const { index, dir } = makeFilm({ video: false, sound: false });
  writeFileSync(join(dir, 'index.html'), '<!doctype html><div data-composition-id="film" data-width="320" data-height="180"></div><script>window.__timelines = {};</script>');
  await assert.rejects(() => openFilm(index, {}), /no timeline/);
  const stuck = makeFilm({ video: false, sound: false, script: 'window.__hf = window.__hf || {}; window.__hf.buildReady = { a: new Promise(() => {}) };' });
  await assert.rejects(() => openFilm(stuck.index, { bootTimeout: 3000 }), /did not finish within|never became ready/);
});

test('engine: page errors are collected, not swallowed', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false, script: 'setTimeout(() => { console.error("bad thing"); }, 10); setTimeout(() => { null.x; }, 20);' });
  const film = await openFilm(index, {});
  try {
    await new Promise((r) => setTimeout(r, 300));
    assert.ok(film.errors.some((e) => /console\.error: bad thing/.test(e)), film.errors.join('|'));
    assert.ok(film.errors.some((e) => /pageerror/.test(e)), film.errors.join('|'));
  } finally { await film.close(); }
});

test('engine: elements added later are bound too (data-var-src, data-var-text)', { skip }, async () => {
  const { index } = makeFilm({ video: false, sound: false });
  const film = await openFilm(index, { variables: { title: 'T2' } });
  try {
    await film.evaluate('(async () => { const d = document.createElement("div"); d.id = "late"; d.setAttribute("data-var-text", "title"); document.body.appendChild(d); await new Promise((r) => setTimeout(r, 50)); })()');
    assert.equal(await film.evaluate('document.getElementById("late").textContent'), 'T2');
  } finally { await film.close(); }
});

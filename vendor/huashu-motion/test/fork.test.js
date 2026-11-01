import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fork, parseSize, reflowNote, resizeRoot } from '../cli/lib/fork.js';
import { comments } from '../cli/lib/inbox.js';
import { OmError } from '../cli/lib/project.js';

const HTML = `<!doctype html>
<html><head><meta name="viewport" content="width=1920, height=1080"></head>
<body><!-- <div data-composition-id="x" data-width="1"> quoted in a comment -->
<div id="film" data-composition-id="film" data-width="1920" data-height='1080' data-fps="30"><p data-width="1920">x</p></div>
</body></html>`;

test('parseSize accepts WxH spellings and rejects odd or silly sizes', () => {
  assert.deepEqual(parseSize('1080x1920'), { width: 1080, height: 1920 });
  assert.deepEqual(parseSize('1080×1920'), { width: 1080, height: 1920 });
  assert.deepEqual(parseSize(' 1080:1080 '), { width: 1080, height: 1080 });
  assert.throws(() => parseSize('1080'), OmError);
  assert.throws(() => parseSize('1081x1920'), /even/);
  assert.throws(() => parseSize('99999x10'), OmError);
});

test('resizeRoot changes only the root size and the viewport meta', () => {
  const html = HTML;
  const r = resizeRoot(html, 1080, 1920);
  assert.match(r.html, /<!-- <div data-composition-id="x" data-width="1"> quoted/);
  assert.deepEqual(r.from, { width: 1920, height: 1080 });
  assert.match(r.html, /<div id="film" data-composition-id="film" data-width="1080" data-height="1920" data-fps="30">/);
  assert.match(r.html, /<p data-width="1920">/); // a child's attribute is not the root's
  assert.match(r.html, /content="width=1080, height=1920"/);
  assert.equal(r.html.length, html.length);
});

test('resizeRoot adds the size when the root has none', () => {
  const r = resizeRoot('<div data-composition-id="a">x</div>', 1080, 1920);
  assert.deepEqual(r.from, { width: null, height: null });
  assert.equal(r.html, '<div data-composition-id="a" data-width="1080" data-height="1920">x</div>');
  assert.throws(() => resizeRoot('<div>x</div>', 10, 10), /data-composition-id/);
});

test('reflowNote asks for a re-layout that fits the new shape', () => {
  const v = reflowNote({ width: 1920, height: 1080 }, { width: 1080, height: 1920 });
  assert.match(v, /横屏（1920×1080）复制来的竖屏版本（1080×1920）/);
  assert.match(v, /9:16/);
  assert.match(v, /不是裁切/);
  assert.match(v, /字幕/);
  const h = reflowNote({ width: 1080, height: 1920 }, { width: 1920, height: 1080 });
  assert.match(h, /竖屏.*横屏版本/);
  assert.match(reflowNote({ width: 1920, height: 1080 }, { width: 3840, height: 2160 }), /3840×2160 版本/);
});

test('fork copies the project without out/ and .om/, resizes it and leaves the re-layout in the inbox', () => {
  const base = mkdtempSync(join(tmpdir(), 'om-fork-'));
  const src = join(base, 'film');
  mkdirSync(join(src, 'out'), { recursive: true });
  mkdirSync(join(src, '.om'), { recursive: true });
  mkdirSync(join(src, 'assets'), { recursive: true });
  writeFileSync(join(src, 'index.html'), '<div id="film" data-composition-id="film" data-width="1920" data-height="1080"></div>');
  writeFileSync(join(src, 'out', 'film-v1.mp4'), 'x');
  writeFileSync(join(src, '.om', 'inbox.jsonl'), '{"type":"comment","id":"cold","text":"old"}\n');
  writeFileSync(join(src, 'assets', 'talk.mp4'), 'x');

  const r = fork(src, join(base, 'film-9x16'), { width: 1080, height: 1920 });
  const dest = join(base, 'film-9x16');
  assert.ok(existsSync(join(dest, 'assets', 'talk.mp4')));
  assert.ok(!existsSync(join(dest, 'out')));
  assert.match(readFileSync(join(dest, 'index.html'), 'utf8'), /data-width="1080" data-height="1920"/);
  assert.match(readFileSync(join(src, 'index.html'), 'utf8'), /data-width="1920"/); // the original is untouched
  const inbox = comments(r.project);
  assert.equal(inbox.length, 1);                    // the old project's comments stay behind
  assert.equal(inbox[0].status, 'pending');
  assert.match(inbox[0].text, /竖屏/);
  assert.throws(() => fork(src, dest, { width: 1080, height: 1920 }), /already exists/);
});

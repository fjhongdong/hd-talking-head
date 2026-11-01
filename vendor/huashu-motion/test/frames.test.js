import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { frameAt, matrixFor, probeVideo, extractClip } from '../cli/lib/frames.js';
import { HAS_FFMPEG, makeFilm } from './fixture-film.js';

test('frames: frameAt picks the last frame at or before the time', () => {
  const pts = [0, 0.1, 0.2, 0.3];
  assert.equal(frameAt(pts, -1), 0);
  assert.equal(frameAt(pts, 0.1), 1);
  assert.equal(frameAt(pts, 0.1985), 1);
  assert.equal(frameAt(pts, 0.1995), 2, 'a time within a millisecond below a frame counts as that frame (float noise)');
  assert.equal(frameAt(pts, 0.2), 2);
  assert.equal(frameAt(pts, 99), 3);
});

test('frames: colour matrix follows the file, else the size', () => {
  assert.equal(matrixFor({ colorSpace: 'bt709', height: 480 }), 'bt709');
  assert.equal(matrixFor({ colorSpace: 'smpte170m', height: 1080 }), 'bt601');
  assert.equal(matrixFor({ height: 720 }), 'bt709');
  assert.equal(matrixFor({ height: 480 }), 'bt601');
});

test('frames: probe, extract the needed range once, reuse it, every frame exists', { skip: !HAS_FFMPEG && 'no ffmpeg' }, async () => {
  const { dir } = makeFilm({ sound: false });
  const file = join(dir, 'assets', 'clip.mp4');
  const info = probeVideo(file);
  assert.equal(info.pts.length, 45); // 1.5 s at 30 fps
  assert.ok(Math.abs(info.pts[1] - 1 / 30) < 1e-3);
  const cache = mkdtempSync(join(tmpdir(), 'om-cache-'));
  const t = await extractClip(file, { from: 0.3, to: 0.9, cacheDir: cache });
  assert.equal(t.ext, 'png');
  assert.equal(t.first, 9);
  assert.equal(t.pts.length, 19); // frames 9..27
  const dirName = readdirSync(cache).find((n) => !n.endsWith('.part') && !n.startsWith('probe-'));
  assert.equal(readdirSync(join(cache, dirName)).filter((n) => n.endsWith('.png')).length, 19);
  assert.ok(existsSync(join(cache, dirName, '00000001.png')));
  const again = await extractClip(file, { from: 0.3, to: 0.9, cacheDir: cache });
  assert.deepEqual(again.pts, t.pts);
  assert.equal(readdirSync(cache).filter((n) => !n.startsWith('probe-')).length, 1, 'the second call reused the cache');
  assert.equal(readdirSync(cache).filter((n) => n.startsWith('probe-')).length, 1, 'and the probe of the file');
});

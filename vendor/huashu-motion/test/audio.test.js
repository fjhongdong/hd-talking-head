import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { checkLoudness, hasAudio, loudness, muxAudio } from '../cli/lib/audio.js';
import { HAS_FFMPEG } from './fixture-film.js';

const skip = !HAS_FFMPEG && 'no ffmpeg';
const ff = (...a) => assert.equal(spawnSync('ffmpeg', ['-v', 'error', '-y', ...a]).status, 0);

function setup() {
  const dir = mkdtempSync(join(tmpdir(), 'om-audio-'));
  const video = join(dir, 'v.mp4');
  ff('-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=30:d=4', '-pix_fmt', 'yuv420p', video);
  const tone = (name, f, vol, d = 4) => { const p = join(dir, name); ff('-f', 'lavfi', '-i', `sine=frequency=${f}:duration=${d}`, '-af', `volume=${vol}`, '-ar', '48000', '-ac', '2', p); return p; };
  return { dir, video, tone };
}

test('audio: one track from 0 is wrapped as it is — the film is as loud as the file', { skip }, () => {
  const { dir, video, tone } = setup();
  const wav = tone('a.wav', 330, 0.3);
  const out = join(dir, 'out.mp4');
  const r = muxAudio(video, [{ file: wav, start: 0, duration: 4, mediaStart: 0, rate: 1, volume: 1 }], out, { duration: 4 });
  assert.equal(r.mode, 'direct');
  assert.ok(hasAudio(out));
  const res = checkLoudness(out, [wav]);
  assert.ok(Math.abs(res.lufs - res.source) < 0.3, `${res.lufs} vs ${res.source}`);
});

test('audio: two tracks are summed without averaging (a plain amix would take ~6 dB off each)', { skip }, () => {
  const { dir, video, tone } = setup();
  const a = tone('a.wav', 330, 0.3), b = tone('b.wav', 523, 0.3);
  const out = join(dir, 'mix.mp4');
  const r = muxAudio(video, [{ file: a, start: 0, duration: 4, mediaStart: 0, rate: 1, volume: 1 }, { file: b, start: 0, duration: 4, mediaStart: 0, rate: 1, volume: 1 }], out, { duration: 4 });
  assert.equal(r.mode, 'mix');
  const alone = loudness(a).lufs, mixed = loudness(out).lufs;
  // two uncorrelated equal tones add 3 dB; averaging would have given -3 dB. Anything above `alone` proves no averaging.
  assert.ok(mixed > alone + 1.5, `mix ${mixed} vs single ${alone}`);
});

test('audio: a track that starts later is delayed, and a quieter data-volume is applied', { skip }, () => {
  const { dir, video, tone } = setup();
  const a = tone('a.wav', 330, 0.3, 2);
  const out = join(dir, 'late.mp4');
  muxAudio(video, [{ file: a, start: 2, duration: 2, mediaStart: 0, rate: 1, volume: 0.5 }], out, { duration: 4 });
  const first = spawnSync('ffmpeg', ['-hide_banner', '-i', out, '-t', '1.5', '-af', 'volumedetect', '-f', 'null', '-'], { encoding: 'utf8' }).stderr;
  const second = spawnSync('ffmpeg', ['-hide_banner', '-ss', '2.2', '-i', out, '-t', '1.5', '-af', 'volumedetect', '-f', 'null', '-'], { encoding: 'utf8' }).stderr;
  assert.ok(/max_volume: -inf/.test(first) || Number(/max_volume: (-?[\d.]+) dB/.exec(first)[1]) < -60, `the first 1.5 s are silent: ${first}`);
  const peak = (txt) => Number(/max_volume: (-?[\d.]+) dB/.exec(txt)[1]);
  const source = peak(spawnSync('ffmpeg', ['-hide_banner', '-i', a, '-af', 'volumedetect', '-f', 'null', '-'], { encoding: 'utf8' }).stderr);
  assert.ok(Math.abs(peak(second) - (source - 6.02)) < 1, `the delayed half is at half volume: ${peak(second)} dB vs source ${source} dB`);
});

test('audio: no tracks gives a silent film; a loudness mismatch is an error, not a delivery', { skip }, () => {
  const { dir, video, tone } = setup();
  const out = join(dir, 'none.mp4');
  assert.equal(muxAudio(video, [], out, { duration: 4 }).mode, 'none');
  assert.equal(hasAudio(out), false);
  const quiet = tone('q.wav', 330, 0.05), loud = tone('l.wav', 330, 0.5);
  muxAudio(video, [{ file: quiet, start: 0, duration: 4, mediaStart: 0, rate: 1, volume: 1 }], join(dir, 'q.mp4'), { duration: 4 });
  assert.throws(() => checkLoudness(join(dir, 'q.mp4'), [loud]), /LUFS but its source/);
});

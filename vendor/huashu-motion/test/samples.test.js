import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { hit, hitStereo, loadPack, packDir, sampler, samplerStereo } from '../cli/lib/samples.js';
import { measurePitch, measureSpectral, noteToMidi } from '../cli/lib/samples-build.js';

const RATE = 48000;
const hasFfmpeg = !spawnSync('ffmpeg', ['-version']).error;
const pack = hasFfmpeg && existsSync(join(packDir(), 'manifest.json')) ? loadPack() : null;
const skip = pack ? false : 'sample pack not built (om samples build) or no ffmpeg';
const det = () => 0; // always the first round robin
const cents = (a, b) => 1200 * Math.log2(a / b);
const peak = (x) => x.reduce((m, v) => Math.max(m, Math.abs(v)), 0);

test('noteToMidi, measurePitch and measureSpectral read a synthetic tone', () => {
  assert.equal(noteToMidi('A4'), 69);
  assert.equal(noteToMidi('A#-1'), 10);
  const x = Float32Array.from({ length: RATE }, (_, i) => Math.sin((2 * Math.PI * 220 * i) / RATE) + 0.4 * Math.sin((2 * Math.PI * 440 * i) / RATE));
  assert.ok(Math.abs(measurePitch(x, RATE) - 57) < 0.02);
  assert.ok(Math.abs(measureSpectral(x, RATE, 57.2) - 57) < 0.05);
});

test('manifest: structure, channels, files on disk', { skip }, () => {
  assert.ok(pack.version >= 2);
  for (const [id, inst] of Object.entries(pack.instruments)) {
    assert.ok(inst.samples.length > 0, id);
    assert.ok([1, 2].includes(inst.channels), `${id} channels`);
    for (const s of [...inst.samples, ...(inst.releases || [])]) {
      assert.ok(existsSync(join(pack.dir, s.file)), `${id}: ${s.file} missing`);
      assert.ok([1, 2].includes(s.ch), `${id}: ch`);
      assert.ok(s.layer != null && s.rr != null);
      if (!inst.drum) assert.ok(Number.isFinite(s.root), `${id}: root`);
    }
    assert.ok(inst.license && inst.credit.length, `${id}: licence/credit`);
  }
});

test('manifest: the pop kit, the electronic kit and the piano are there', { skip }, () => {
  for (const id of ['pk_kick', 'pk_snare', 'pk_rim', 'pk_hat', 'pk_ohat', 'pk_tom', 'pk_crash', 'pk_ride', 'ek_kick', 'ek_snare', 'ek_clap', 'ek_hat', 'ek_ohat']) {
    assert.ok(pack.instruments[id]?.samples.length, id);
    assert.ok(pack.instruments[id].drum, `${id} should be unpitched`);
  }
  for (const id of ['pk_kick', 'pk_snare', 'pk_hat']) {
    const layers = new Set(pack.instruments[id].samples.map((s) => s.layer));
    assert.ok(layers.size >= 2, `${id}: two velocity layers`);
    assert.ok(pack.instruments[id].samples.length >= 4, `${id}: round robins`);
    assert.equal(pack.instruments[id].channels, 2, `${id}: stereo`);
  }
  const piano = pack.instruments.piano, roots = piano.samples.map((s) => s.root);
  assert.ok(Math.min(...roots) <= 24 && Math.max(...roots) >= 108, 'piano covers A0 to C8');
  assert.ok(new Set(piano.samples.map((s) => s.layer)).size >= 2, 'piano layers');
  assert.ok(piano.releases?.length > 0, 'piano release samples');
  for (const id of ['violins', 'violas', 'celli', 'basses']) assert.ok(new Set(pack.instruments[id].samples.map((s) => s.layer)).size >= 2, `${id} layers`);
});

test('manifest: whole pack stays within 60 MB', { skip }, () => {
  let bytes = 0;
  for (const inst of Object.values(pack.instruments)) for (const s of [...inst.samples, ...(inst.releases || [])]) bytes += statSync(join(pack.dir, s.file)).size;
  assert.ok(bytes <= 60e6, `${(bytes / 1e6).toFixed(1)} MB`);
});

test('sampler: mono stays a Float32Array, samplerStereo gives { L, R } that folds to the mono voice', { skip }, () => {
  const mono = sampler('piano')(261.63, 1, 0.7, det), st = samplerStereo('piano')(261.63, 1, 0.7, det);
  assert.ok(mono instanceof Float32Array);
  assert.ok(st.L instanceof Float32Array && st.R instanceof Float32Array);
  assert.equal(st.L.length, mono.length);
  assert.equal(st.R.length, mono.length);
  assert.ok(peak(mono) > 0.01);
  let worst = 0, side = 0;
  for (let i = 0; i < mono.length; i++) { worst = Math.max(worst, Math.abs((st.L[i] + st.R[i]) / 2 - mono[i])); side = Math.max(side, Math.abs(st.L[i] - st.R[i])); }
  assert.ok(worst < 1e-5, `fold-down differs by ${worst}`);
  assert.ok(side > 0.001, 'a stereo recording should have a stereo image');
});

test('sampler: a mono recording comes back as the same array on both sides', { skip }, () => {
  const v = samplerStereo('guitar')(220, 1, 0.7, det);
  assert.equal(v.L, v.R);
  assert.ok(peak(v.L) > 0.01);
});

test('sampler: velocity picks louder layers; unknown instrument is null', { skip }, () => {
  const p = sampler('piano'), soft = peak(p(261.63, 1, 0.1, det)), loud = peak(p(261.63, 1, 1, det));
  assert.ok(loud > soft * 1.5, `${soft} vs ${loud}`);
  assert.equal(sampler('nope'), null);
  assert.equal(samplerStereo('nope'), null);
  assert.equal(hit('nope'), null);
  assert.equal(hitStereo('nope'), null);
});

test('sampler: { release: true } lays the key-release noise after the note', { skip }, () => {
  const plain = sampler('piano')(261.63, 1, 0.8, det), rel = sampler('piano', { release: true })(261.63, 1, 0.8, det);
  assert.ok(rel.length > plain.length + 2000, `${rel.length} vs ${plain.length}`);
  const tail = rel.slice(plain.length + 1000), tailPeak = peak(tail);
  assert.ok(tailPeak > 1e-4, 'the release part should not be silent');
  // no release for an instrument that has none: same length as the plain voice
  assert.equal(sampler('harp', { release: true })(440, 1, 0.7, det).length, sampler('harp')(440, 1, 0.7, det).length);
});

test('hit: every drum voice is audible; stereo variant matches mono fold', { skip }, () => {
  for (const [id, inst] of Object.entries(pack.instruments)) {
    if (!inst.drum) continue;
    const m = hit(id)(det, 0.9), s = hitStereo(id)(det, 0.9);
    assert.ok(m instanceof Float32Array && m.length > 1000, id);
    assert.ok(peak(m) > 0.02, `${id} is silent`);
    assert.equal(s.L.length, m.length);
    if (inst.channels === 1) assert.equal(s.L, s.R, id);
  }
  const k = hitStereo('pk_snare')(det, 0.9);
  let side = 0;
  for (let i = 0; i < k.L.length; i++) side = Math.max(side, Math.abs(k.L[i] - k.R[i]));
  assert.ok(side > 0.001, 'the pop kit should be wider than mono');
});

test('resample: a pitched piano sample is within 10 cents after shifting', { skip }, () => {
  const v = sampler('piano');
  for (const midi of [40.4, 52.3, 60.37, 66.5, 72.45, 79.3, 88.2]) {
    const f = 440 * 2 ** ((midi - 69) / 12), x = v(f, 1.5, 0.7, det);
    const got = measurePitch(x, RATE);
    assert.ok(got != null, `midi ${midi}: no pitch found`);
    const err = cents(440 * 2 ** ((got - 69) / 12), f);
    assert.ok(Math.abs(err) < 10, `midi ${midi}: ${err.toFixed(1)} cents off`);
  }
});

// Timeline: 120 BPM (1 beat 0.5 s, 1 bar 2 s). Each "time window" has its own city-clock start and time-lapse rate curve (rate changing over time = speed ramp)
import { clamp, ss } from '/core/lib.js';

export const BPM = 120, BEAT = .5, BAR = 2;
export const DUR = 38;
export const T = {
  vo: { v1: .9, v2: 9.6, v3: 14.3, v4: 19.4, v5: 25.9, v6: 30.6 },
  firstNote: 3.0, secondNote: 4.5,
  title0: 5.0,                       // title letters: one lights every 0.25 s
  greenA: 10.0, greenB: 12.0,        // junction light change
  trainStop: 17.0, trainGo: 18.6,
  jamHorn: [20.0, 22.0],
  rampDown: [22.5, 24.0], rampUp: [30.0, 30.6],
  hops: [24.8, 25.6, 26.4, 27.1, 27.8, 29.4],   // mother duck, ducklings 1–3, duckling 4's first (failed) try, success
  release: 30.0, finalChord: 34.0, end: 34.0,
};
export const SHOTS = [
  [0, 5, 'dawn'], [5, 9, 'title'], [9, 14, 'ix'], [14, 19, 'train'], [19, 24, 'jam'], [24, 30, 'ducks'], [30, 34, 'rise'], [34, 38, 'end'],
];
export const shotAt = t => SHOTS.find(s => t < s[1]) || SHOTS[SHOTS.length - 1];

// Time windows: clock0 = city clock at the window start (seconds since 6:00); rate(t) = time-lapse rate
const jamRate = t => {
  if (t < T.rampDown[0]) return 40;
  if (t < T.rampDown[1]) { const u = (t - T.rampDown[0]) / (T.rampDown[1] - T.rampDown[0]); return 1 + 39 * (1 - ss(u)); }
  if (t < T.rampUp[0]) return 1;
  if (t < T.rampUp[1]) { const u = (t - T.rampUp[0]) / (T.rampUp[1] - T.rampUp[0]); return 1 + 39 * ss(u); }
  return 40;
};
export const WINDOWS = [
  { name: 'dawn', t0: 0, t1: 5, clock0: 0, rate: () => 4 },
  { name: 'title', t0: 5, t1: 9, clock0: 15 * 60, rate: () => 240 },
  { name: 'ix', t0: 9, t1: 14, clock0: 72 * 60, rate: () => 24 },
  { name: 'train', t0: 14, t1: 19, clock0: 99 * 60 + 25, rate: () => 6 },
  { name: 'jam', t0: 19, t1: DUR + .5, clock0: 118 * 60, rate: jamRate },
];
// Pre-integration (1 ms steps, deterministic)
for (const W of WINDOWS) {
  const n = Math.ceil((W.t1 - W.t0) * 1000) + 1, tab = new Float64Array(n); let acc = 0;
  for (let i = 0; i < n; i++) { tab[i] = acc; const t = W.t0 + i / 1000; acc += (W.rate(t) + W.rate(t + .001)) / 2 / 1000; }
  W.tab = tab;
}
export const windowAt = t => WINDOWS.find(w => t < w.t1) || WINDOWS[WINDOWS.length - 1];
export function clockAt(t, W = windowAt(t)) {
  const f = clamp((t - W.t0) * 1000, 0, W.tab.length - 1), i = Math.floor(f), u = f - i;
  const a = W.tab[i], b = W.tab[Math.min(i + 1, W.tab.length - 1)];
  return W.clock0 + a + (b - a) * u;
}
export const fmtClock = c => { const s = Math.floor(c) + 6 * 3600, h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60; return [String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0'), String(x).padStart(2, '0')]; };

export const VO = [
  { id: 'v1', t: T.vo.v1, text: 'Six a.m. One car. One note.' },
  { id: 'v2', t: T.vo.v2, text: 'Every green light adds a beat.' },
  { id: 'v3', t: T.vo.v3, text: 'The seven-forty brings the bass.' },
  { id: 'v4', t: T.vo.v4, text: 'By eight, the whole town is playing.' },
  { id: 'v5', t: T.vo.v5, text: 'Every song needs a rest.' },
  { id: 'v6', t: T.vo.v6, text: 'Then… take it from the top.' },
];
export const TITLE = 'TOY TOWN RUSH HOUR';

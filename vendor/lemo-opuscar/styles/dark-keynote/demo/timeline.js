// timeline.js — tempo grid + figure + note tables of the three voices (the single data source shared by picture / score / mix / self-check)
export const BPM = 120, BEAT = 0.5, BAR = 2, S16 = 0.125, DUR = 42;

// Figure P (original, 12 sixteenth notes): A3 E4 B4 E4 C#5 E4 | A3 E4 B4 E4 D5 C#5
export const P = [57, 64, 71, 64, 73, 64, 57, 64, 71, 64, 74, 73];

// Key times (seconds)
export const K = {
  typeStart: 0.75,          // first character of the title
  title: 'Room to think.',
  ret: 2.5,                 // return key
  typeI: 2.75,              // "I" on the second line
  ding: [3.0, 3.5, 3.75],   // three notification dings
  pullStart: 4.0, pullEnd: 12.0,
  vo: { l1: 4.25, l2: 6.25, l3: 8.25, l4: 20.5, l5: 23.0, l6: 34.55 },
  inserts: [12.0, 12.5, 13.0, 13.5],
  drown: 13.5,
  freeze: 15.0, stretch: 15.5, press: 16.0, gridShow: 17.0,
  sort: 18.0, chrome: 19.0, dim: 19.5,
  reveal: 20.0, checks: [21.75, 22.25, 22.75], rotZero: 24.5, pushNum: 25.0,
  num: 26.0, locks: [26.5, 26.625, 26.75, 26.875, 27.0], files: 27.0, line2: 28.0,
  numBack: 29.5, retract: [30.0, 30.5, 31.0, 31.5, 32.0], toCaret: 32.5,
  silence2: 33.0, echo: 34.0, echoType: 34.5, endCard: 37.0, endFade: 40.0, caretOff: 41.5,
};

// Voice 1: marimba on the beat (4.0–15.0)
export function voice1() {
  const out = [];
  for (let k = 0; ; k++) { const t = 4.0 + k * S16; if (t >= K.freeze - 1e-6) break; out.push({ t, k, i: k % 12, m: P[k % 12] }); }
  return out;
}
// Voice 2: the same figure, enters at 6.0, from 8.0 speeds up and phases (speed ratio rate2)
export function rate2(t) {
  if (t < 8) return 1;
  if (t < 10) return 1 + 0.045 * (t - 8) / 2;
  if (t < 14) return 1.045 + 0.02 * (t - 10) / 4;
  return 1.065 + 0.10 * (t - 14);           // 14–15 rushes up to 1.165
}
function notesByRate(t0, rate, filter, tEnd = K.freeze) {
  const out = []; let tau = 0, t = t0, k = 0; const dt = 1 / 2000;
  while (t < tEnd - 1e-6) {
    if (tau >= k * S16 - 1e-9) { if (filter(k)) out.push({ t: Math.round(t * 2000) / 2000, k, i: k % 12, m: P[k % 12] }); k++; continue; }
    tau += rate(t) * dt; t += dt;
  }
  return out;
}
export function voice2() { return notesByRate(6.0, rate2, () => true); }
// Voice 3: glockenspiel, plays only the high notes (notes 2, 4, 10, 11), enters at 10.0, slightly slower (phasing the other way)
export function voice3() {
  return notesByRate(10.0, t => t < 14 ? 0.94 : 0.94 + 0.12 * (t - 14), k => [2, 4, 10, 11].includes(k % 12)).map(n => ({ ...n, m: n.m + 12 }));
}
// The clean voice after alignment (18–26 played lightly; 30–33 subtraction)
export function voiceClean() {
  const out = [];
  for (let k = 0; ; k++) { const t = 18.0 + k * S16; if (t >= 26.0 - 1e-6) break; out.push({ t, k, i: k % 12, m: P[k % 12], v: t < 20 ? 0.55 : 0.32 }); }
  // Subtraction: 30–31 remove 4, 31–32 remove 8, 32–33 only the quarter-note A4 left
  const drop1 = [1, 5, 8, 11], drop2 = [1, 2, 3, 5, 7, 8, 9, 11];
  for (let k = 0; k < 16; k++) { const t = 30 + k * S16, i = k % 12; if (!drop1.includes(i)) out.push({ t, k, i, m: P[i], v: 0.36 }); }
  for (let k = 0; k < 8; k++) { const t = 31 + k * S16 * 2, i = (k * 2) % 12; if (!drop2.includes(i)) out.push({ t, k, i, m: P[i], v: 0.3 }); }
  for (let k = 0; k < 2; k++) out.push({ t: 32 + k * 0.5, k, i: 0, m: 69, v: 0.26 });
  return out.sort((a, b) => a.t - b.t);
}
export const typeTimes = (t0, text) => [...text].map((c, i) => ({ c, t: t0 + i * S16 }));

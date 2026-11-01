// The character "水" (water): its skeleton is the glyph of the OFL kaishu (楷书, regular script) font Ma Shan Zheng.
// The centrelines of the four strokes (vertical hook, horizontal-then-left-falling, left-falling, right-falling press) are traced from the glyph, with brush pressure matching the glyph's stroke thickness; the brush engine writes them one by one in stroke order, and the result is finally clipped by the glyph outline (slightly expanded),
// so stroke order, lift-and-press and feibai (飞白, dry-brush streaks) come from the engine, while the character's structure and centre of gravity come from the calligraphic glyph. Coordinates are in a 100×100 character cell; the third number is brush pressure.
import { mk, draw, TONE } from './ink.js';
import { lerp, clamp } from '/core/lib.js';

export const SHUI = [
  // Vertical hook: start with a concealed tip (藏锋), lift slightly in the middle, gather force at the bottom, then flick the hook out to the upper left
  [[42.5, 7.5, .7], [44.5, 9.5, 1.1], [44.8, 18, .95], [45, 38, .9], [45.3, 58, .92], [45.4, 76, 1.0], [44, 87, 1.12], [40.5, 90.5, 1.0], [35, 84, .7], [29, 76.5, .25]],
  // Horizontal-then-left-falling: cut in with the brush, a short horizontal rising to the right, press and pause at the turn, then the left-falling stroke exits to the lower left with a sharp tip
  [[12, 53, .6], [16, 49, .9], [24, 45.5, .85], [32, 42.5, .95], [37.5, 42.5, 1.15], [37.5, 49, 1.05], [33, 60, .95], [26, 70, .8], [17, 80, .55], [8, 87.5, .18]],
  // Left-falling: start at upper right, go to lower left
  [[74.5, 26.5, .8], [74, 31, 1.05], [68, 38, .9], [60, 44.5, .72], [53.5, 48.5, .5]],
  // Right-falling press (捺): start light, grow heavy, the press foot exits flat
  [[53, 48, .45], [58, 55, .62], [66, 63, .82], [74.5, 69.5, 1.0], [83, 74.5, 1.22], [90, 77, 1.05], [95.5, 77.5, .3]],
];
const WID = [8.2, 8.4, 8.5, 11];       // base width of each stroke (character-cell units)

// Glyph mask (aligned with box)
const maskCache = {};
export function glyphMask(box, W = 1920, H = 1080) {
  const key = box.join(',');
  if (maskCache[key]) return maskCache[key];
  const [x0, y0, S] = box, cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const c = cv.getContext('2d');
  c.font = `${S}px MaShanZheng`; c.textAlign = 'center'; c.textBaseline = 'alphabetic';
  const m = c.measureText('水'), y = y0 + S / 2 + (m.actualBoundingBoxAscent - m.actualBoundingBoxDescent) / 2;
  c.fillStyle = '#000'; c.fillText('水', x0 + S / 2, y);
  c.strokeStyle = '#000'; c.lineWidth = S * .014; c.lineJoin = 'round'; c.strokeText('水', x0 + S / 2, y);   // slightly expanded, leaves a little room for the feibai's ragged edges
  return (maskCache[key] = cv);
}

export function shuiStrokes(box, o = {}) {
  const [x0, y0, sz] = box, k = sz / 100;
  return SHUI.map((st, i) => mk(st.map(p => [x0 + p[0] * k, y0 + p[1] * k, p[2]]), {
    w: WID[i] * k * (o.wk ?? 1.12), tone: TONE.jiao, dry: o.dry ?? .17, wet: o.wet ?? .35, prof: 'even', rough: .06, nb: 48, solid: true, seed: (o.seed ?? 51) * 10 + i,
  }));
}

// Cutting the current: the character leaves along the press stroke's momentum, flattens and sweeps right out of frame (feibai)
export function cutStroke(box, x1, y1, o = {}) {
  const [x0, y0, sz] = box, k = sz / 100;
  const P = [[62, 59, .45], [70, 66.5, .7], [79, 72.5, .92], [88, 76.5, 1.02]].map(p => [x0 + p[0] * k, y0 + p[1] * k, p[2]]);
  const last = P[P.length - 1];
  const n = 7;
  for (let i = 1; i <= n; i++) {
    const u = i / n;
    P.push([lerp(last[0], x1, u), lerp(last[1], y1, Math.pow(u, .55)) + Math.sin(u * 3.1) * 5 * k, 1.05 + .15 * Math.sin(u * 2.2) - .4 * Math.pow(u, 3)]);
  }
  return mk(P, { w: (o.w ?? 13) * k, tone: TONE.jiao, dry: o.dry ?? .62, wet: .15, prof: 'even', rough: .16, nb: 64, solid: true, seed: o.seed ?? 777 });
}

// Write the character by progress: prog[i] ∈ [0,1] is how far stroke i has been written; T is the temporary layer {wet, dry, col contexts + canvases}; when written, clip with the glyph outline and paste onto the target layer
export function writeShui(dst, T, box, prog, o = {}) {
  const S = o.strokes || shuiStrokes(box, o);
  for (const c of [T.ink.wet, T.ink.dry]) { c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1; c.clearRect(0, 0, T.wet.width, T.wet.height); }
  let any = false;
  S.forEach((s, i) => { if ((prog[i] ?? 0) > 0) { draw(T.ink, s, prog[i], o.am ?? 1); any = true; } });
  if (!any) return S;
  const mask = glyphMask(box, T.wet.width, T.wet.height);
  for (const key of ['wet', 'dry']) {
    const c = T.ink[key]; c.globalCompositeOperation = 'destination-in'; c.drawImage(mask, 0, 0); c.globalCompositeOperation = 'source-over';
    const d = dst[key]; d.save(); d.setTransform(1, 0, 0, 1, 0, 0); if (o.dx || o.dy || o.alpha != null) { d.globalAlpha = o.alpha ?? 1; } d.drawImage(T[key], o.dx || 0, o.dy || 0); d.restore();
  }
  return S;
}

// Sword-tip position: where the brush tip is when stroke i has been written to p (used to aim the swordsman's arm)
export function tipAt(S, i, p) {
  const s = S[i], m = (s.n - 1) * clamp(p), k = Math.floor(m), f = m - k, a = s.P[k], b = s.P[Math.min(s.n - 1, k + 1)];
  return [lerp(a[0], b[0], f), lerp(a[1], b[1], f)];
}

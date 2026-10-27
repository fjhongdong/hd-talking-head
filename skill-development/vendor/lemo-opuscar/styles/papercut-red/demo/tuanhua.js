// Tuanhua (团花, round folded-and-cut rosette): cut through 8 folded layers (D4 symmetry). Only one 45° wedge is designed, then mirrored 8 times; the fold / unfold animation uses the same wedge.
// units: radius R = 400; origin = paper centre; wedge θ ∈ [0, π/4] (canvas y points down, θ clockwise)
import { PAL, canvas, piece, finishPaper, fill, cut, cutTaper, trace, curve } from './paper.js';
import { sawRow, crescent, crescentPts, swirl, plum, rosette, dots, along } from './motifs.js';

export const TR = 400;
const Q = Math.PI / 4;
const pol = (r, a) => [Math.cos(a) * r, Math.sin(a) * r];
// outer outline: 16-lobed scalloped edge + fine sawtooth
export function outerR(a) { const k = Math.abs(Math.cos(a * 8)); return TR * (.9 + .1 * Math.pow(k, .6)); }
function wedgePoly(m = .012) {
  const pts = [[0, 0]];
  for (let i = 0; i <= 90; i++) { const a = -m + (Q + 2 * m) * i / 90; pts.push(pol(outerR(a), a)); }
  return pts;
}
// all cut patterns inside the wedge (called after fill). The middle ring is yangke (阳刻, relief cut: cut away, leaving only a net of red lines); the inner and outer rings are yinke (阴刻, intaglio cut: holes cut into a red surface)
export function wedgeCuts(g, opt = {}) {
  const R = TR, mid = Q / 2, col = g.__col || PAL.red;
  const red = (w, fn) => { g.save(); g.globalCompositeOperation = 'source-over'; g.strokeStyle = col; g.lineWidth = w; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); fn(g); g.stroke(); g.restore(); };
  const redFill = fn => { g.save(); g.globalCompositeOperation = 'source-over'; g.fillStyle = col; g.beginPath(); fn(g); g.fill(); g.restore(); };
  const arcPts = (r, a0, a1, n = 24) => { const o = []; for (let i = 0; i <= n; i++) o.push(pol(r, a0 + (a1 - a0) * i / n)); return o; };
  // —— flower centre: eight petals (×8) + centre hole + a ring of small triangular holes
  cut(g, q => {
    const P = (u, v) => [Math.cos(mid) * u - Math.sin(mid) * v, Math.sin(mid) * u + Math.cos(mid) * v];
    q.moveTo(...P(R * .045, 0)); q.quadraticCurveTo(...P(R * .12, R * .075), ...P(R * .21, 0)); q.quadraticCurveTo(...P(R * .12, -R * .075), ...P(R * .045, 0));
  });
  cut(g, q => { q.moveTo(R * .026, 0); q.arc(0, 0, R * .026, 0, Math.PI * 2); });
  for (const a of [Q * .18, Q * .82]) cut(g, q => { const p0 = pol(R * .16, a); q.moveTo(...p0); q.arc(...p0, R * .018, 0, 7); });
  cut(g, q => trace(q, crescentPts(0, 0, R * .29, mid - .32, mid + .32, R * .05, 16)));
  for (const a of [0, Q]) cut(g, q => trace(q, crescentPts(0, 0, R * .29, a - .12, a + .12, R * .03, 8)));
  sawRow(g, curve([pol(R * .335, -.02), pol(R * .335, mid), pol(R * .335, Q + .02)], false, 2), R * .045, R * .02, -1, .72);
  // —— middle ring: the whole band cut away, leaving red lines (yangke)
  const r0 = R * .38, r1 = R * .69;
  cut(g, q => { const A = arcPts(r0, -.05, Q + .05), B = arcPts(r1, Q + .05, -.05); trace(q, A.concat(B)); });
  red(R * .016, q => { trace(q, arcPts(r0 + R * .006, -.05, Q + .05), false); });
  red(R * .016, q => { trace(q, arcPts(r1 - R * .006, -.05, Q + .05), false); });
  // red sawtooth on the ring edges (tooth tips pointing into the empty area)
  for (const [r, s] of [[r0 + R * .012, 1], [r1 - R * .012, -1]]) {
    const S = along(arcPts(r, -.03, Q + .03, 40), R * .03);
    redFill(q => { for (let i = 0; i < S.length - 1; i++) { const A = S[i], B = S[i + 1], m = [(A.x + B.x) / 2, (A.y + B.y) / 2], d = Math.hypot(m[0], m[1]), n = [m[0] / d * s, m[1] / d * s]; q.moveTo(A.x, A.y); q.lineTo(B.x, B.y); q.lineTo(m[0] + n[0] * R * .032, m[1] + n[1] * R * .032); q.closePath(); } });
  }
  // ruyi cloud curls (如意云卷) on the fold line (red lines, paired after mirroring)
  for (const [a, dir] of [[0, 1], [Q, -1]]) {
    const c = pol(R * .535, a), pts = [], n = 60;
    for (let i = 0; i <= n; i++) { const u = i / n, an = a + dir * (Math.PI * .5 + u * Math.PI * 2.1), rr = R * .085 * (1 - u * .85); pts.push([c[0] + Math.cos(an) * rr, c[1] + Math.sin(an) * rr]); }
    red(R * .014, q => trace(q, pts, false));
    red(R * .014, q => { const s0 = pts[0]; q.moveTo(...s0); q.lineTo(...pol(r1 - R * .01, a)); });
    red(R * .014, q => { const p1 = pol(R * .535 - R * .085, a); q.moveTo(...p1); q.lineTo(...pol(r0 + R * .01, a)); });
  }
  // lantern (red surface + windows between the ribs), hanging cord above connects to the inner ring, tassel below connects to the outer ring
  lanternPos(g, R * .535, mid, R * .2, R * .15, col, red, redFill);
  // small plum blossoms (red) dotted on both sides of the lantern
  for (const a of [mid - .24, mid + .24]) { const c = pol(R * .6, a); redFill(q => { for (let k = 0; k < 5; k++) { const an = k * Math.PI * 2 / 5, p = [c[0] + Math.cos(an) * R * .016, c[1] + Math.sin(an) * R * .016]; q.moveTo(p[0] + R * .014, p[1]); q.arc(p[0], p[1], R * .014, 0, 7); } }); cut(g, q => q.arc(c[0], c[1], R * .007, 0, 7)); red(R * .008, q => { q.moveTo(...c); q.lineTo(...pol(R * .64, a + (a < mid ? .08 : -.08))); }); }
  // —— outer ring: one fan of radiating leaf veins per lobe + crescents
  for (const pa of [Q * .25, Q * .75]) {
    const base = pol(R * .72, pa);
    for (let k = -3; k <= 3; k++) { const an = pa + k * .055, L = R * (.13 - Math.abs(k) * .012); const p0 = pol(R * .735, pa + k * .02), p1 = [p0[0] + Math.cos(an) * L, p0[1] + Math.sin(an) * L], pm = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2]; cutTaper(g, [p0, pm, p1], R * .022); }
    cut(g, q => trace(q, crescentPts(...pol(R * .74, pa), R * .06, pa + Math.PI - 1.1, pa + Math.PI + 1.1, R * .02, 10)));
  }
  for (const a of [0, Q]) plum(g, ...pol(R * .8, a), R * .032, a);
  plum(g, ...pol(R * .79, mid), R * .026, mid);
  // fine sawtooth on the outer edge
  const edge = []; for (let i = 0; i <= 60; i++) { const a = -.01 + (Q + .02) * i / 60; edge.push(pol(outerR(a) - R * .03, a)); }
  sawRow(g, edge, R * .026, R * .016, 1, .7);
}
// yangke lantern: red lantern body (windows between the ribs) + caps + hanging cord + tassel
function lanternPos(g, r, a, h, w, col, red, redFill) {
  const c = pol(r, a), ux = Math.cos(a), uy = Math.sin(a), vx = -uy, vy = ux;
  const P = (u, v) => [c[0] + ux * u + vx * v, c[1] + uy * u + vy * v];
  const body = []; for (let i = 0; i <= 40; i++) { const t = i / 40 * Math.PI * 2; body.push(P(Math.cos(t) * h * .5, Math.sin(t) * w * .5)); }
  redFill(q => trace(q, body));
  // windows between the ribs: 4 crescent-shaped vertical windows
  for (const v of [-.36, -.12, .12, .36]) {
    const pts = []; for (let i = 0; i <= 16; i++) { const u = -h * .38 + h * .76 * i / 16, b = Math.sqrt(Math.max(0, 1 - (u / (h * .5)) ** 2)); pts.push(P(u, v * w * b)); }
    cutTaper(g, pts, w * .13);
  }
  // lantern caps
  redFill(q => { const A = P(-h * .5 - h * .07, -w * .24), B = P(-h * .5 - h * .07, w * .24), C = P(-h * .5 + h * .03, w * .3), D = P(-h * .5 + h * .03, -w * .3); q.moveTo(...A); q.lineTo(...B); q.lineTo(...C); q.lineTo(...D); q.closePath(); });
  redFill(q => { const A = P(h * .5 + h * .07, -w * .2), B = P(h * .5 + h * .07, w * .2), C = P(h * .5 - h * .03, w * .28), D = P(h * .5 - h * .03, -w * .28); q.moveTo(...A); q.lineTo(...B); q.lineTo(...C); q.lineTo(...D); q.closePath(); });
  // hanging cord (to the inner ring) and tassel (to the outer ring)
  red(w * .08, q => { q.moveTo(...P(-h * .56, 0)); q.lineTo(...pol(TR * .385, a)); });
  red(w * .07, q => { q.moveTo(...P(h * .56, 0)); q.lineTo(...pol(TR * .685, a)); });
  for (const v of [-.14, .14]) red(w * .05, q => { q.moveTo(...P(h * .58, 0)); q.lineTo(...P(h * .78, v * w)); });
}
// flat red wedge texture (no texture, used for compositing)
const CACHE = {};
export function wedgeFlat(K = 2.4, col = PAL.red) {
  const key = K + col; if (CACHE[key]) return CACHE[key];
  const p = piece([-10, -10, TR + 10, TR * .75 + 10], g => {
    g.__col = col;
    fill(g, q => trace(q, wedgePoly()), col);
    wedgeCuts(g);
    g.save(); g.globalCompositeOperation = 'destination-in'; g.beginPath(); trace(g, wedgePoly(.012)); g.fill(); g.restore();
  }, { ss: K, tex: false, edge: 0, col });
  CACHE[key] = p; return p;
}
// the 8 transforms of D4 (applied to the wedge): R(kπ/2) and R(kπ/2)·mirror(about π/4)
export const D4 = [];
for (let k = 0; k < 4; k++) { const c = Math.round(Math.cos(k * Math.PI / 2)), s = Math.round(Math.sin(k * Math.PI / 2)); D4.push([c, s, -s, c, 0, 0]); D4.push([c * 0 + -s * 1, s * 0 + c * 1, c * 1 + -s * 0, s * 1 + c * 0, 0, 0]); }
// the whole tuanhua (with texture and cut edges): returned as a piece, centred at the origin
export function tuanhua(K = 2.4, col = PAL.red, seed = 61) {
  const key = 'full' + K + col; if (CACHE[key]) return CACHE[key];
  const W = TR * 2 + 20, [c, g] = canvas(W * K, W * K), w = wedgeFlat(K, col);
  for (const M of D4) {
    g.setTransform(K, 0, 0, K, W * K / 2, W * K / 2); g.transform(...M);
    g.drawImage(w.c, w.x0, w.y0, w.w, w.h);
  }
  finishPaper(c, g, { seed });
  const p = { c, x0: -W / 2, y0: -W / 2, w: W, h: W, K, col };
  CACHE[key] = p; return p;
}
// hole mask (holes inside the circle = white, paper = transparent, outside the circle = transparent), used for projected light and glow
export function tuanhuaHoles(K = 1.2) {
  const key = 'holes' + K; if (CACHE[key]) return CACHE[key];
  const t = tuanhua(K), [c, g] = canvas(t.c.width, t.c.height);
  g.setTransform(K, 0, 0, K, -t.x0 * K, -t.y0 * K);
  g.beginPath(); for (let i = 0; i <= 256; i++) { const a = i / 256 * Math.PI * 2, r = outerR(a) - 2; const p = pol(r, a); if (i) g.lineTo(...p); else g.moveTo(...p); } g.fillStyle = '#fff'; g.fill();
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'destination-out'; g.drawImage(t.c, 0, 0);
  const p = { c, x0: t.x0, y0: t.y0, w: t.w, h: t.h }; CACHE[key] = p; return p;
}

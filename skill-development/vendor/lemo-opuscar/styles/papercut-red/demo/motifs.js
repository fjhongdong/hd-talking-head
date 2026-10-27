// Library of folk paper-cut motifs (all are "cut away" operations, used in the piece coordinates of the caller)
// sawtooth, crescent, cloud / swirl, plum-blossom holes, copper-coin holes, fish scales, carved lines
import { cut, cutLine, cutTaper, curve, trace } from './paper.js';

const TAU = Math.PI * 2;
// resample a polyline by arc length, returns [{x,y,nx,ny}] (normal points to the left of the direction of travel)
export function along(pts, step) {
  const L = [0]; for (let i = 1; i < pts.length; i++) L.push(L[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const tot = L[L.length - 1], n = Math.max(1, Math.round(tot / step)), out = [];
  let j = 0;
  for (let k = 0; k <= n; k++) {
    const s = tot * k / n; while (j < pts.length - 2 && L[j + 1] < s) j++;
    const u = (s - L[j]) / ((L[j + 1] - L[j]) || 1), a = pts[j], b = pts[j + 1], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    out.push({ x: a[0] + dx * u, y: a[1] + dy * u, nx: dy / l, ny: -dx / l, tx: dx / l, ty: dy / l, s });
  }
  return out;
}
// sawtooth pattern: cut a row of long thin triangular holes along a line (points toward side), leaving thin red teeth
export function sawRow(g, pts, h = 10, sp = 6, side = 1, gapFrac = .78) {
  const S = along(pts, sp);
  cut(g, q => {
    for (let i = 0; i < S.length - 1; i++) {
      const a = S[i], b = S[i + 1], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, hw = gapFrac / 2;
      const p0 = [a.x + (b.x - a.x) * (.5 - hw), a.y + (b.y - a.y) * (.5 - hw)], p1 = [a.x + (b.x - a.x) * (.5 + hw), a.y + (b.y - a.y) * (.5 + hw)];
      q.moveTo(p0[0], p0[1]); q.lineTo(p1[0], p1[1]); q.lineTo(mx + a.nx * h * side, my + a.ny * h * side); q.closePath();
    }
  });
}
// sawtooth edge: turn an edge into a sawtooth outline (returns a new polyline, used to build outer outlines)
export function sawEdge(pts, h = 12, sp = 14, side = 1, jit = 0, seed = 0) {
  const S = along(pts, sp / 2), out = [];
  S.forEach((p, i) => { const k = i % 2 ? h * side * (1 + jit * (Math.sin(i * 12.9898 + seed) * .5)) : 0; out.push([p.x + p.nx * k, p.y + p.ny * k]); });
  return out;
}
// crescent: arc-shaped hole, thick in the middle and pointed at both ends. c = centre, r = radius, a0..a1 = arc span, t = maximum thickness
export function crescentPts(cx, cy, r, a0, a1, t, n = 18) {
  const o = [], ins = [];
  for (let i = 0; i <= n; i++) { const u = i / n, a = a0 + (a1 - a0) * u, k = Math.sin(Math.PI * u); o.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); ins.push([cx + Math.cos(a) * (r - t * k), cy + Math.sin(a) * (r - t * k)]); }
  return o.concat(ins.reverse());
}
export function crescent(g, cx, cy, r, a0, a1, t) { cut(g, q => trace(q, crescentPts(cx, cy, r, a0, a1, t))); }
// crescent pattern (scales): rows of staggered crescent holes, opening upward (rot rotates them)
export function crescentRows(g, x0, y0, x1, y1, r = 12, t = 4, rot = 0, span = .7) {
  const c = Math.cos(rot), s = Math.sin(rot);
  cut(g, q => {
    let row = 0;
    for (let y = y0 - r; y < y1 + r * 2; y += r * 1.05, row++)
      for (let x = x0 - r * 2 + (row % 2) * r; x < x1 + r * 2; x += r * 2) {
        const pts = crescentPts(0, 0, r, Math.PI * (.5 - span / 2), Math.PI * (.5 + span / 2), t, 12)
          .map(([u, v]) => [x + u * c - v * s, y + u * s + v * c]);
        trace(q, pts);
      }
  });
}
// swirl pattern: Archimedean-spiral carved line (tapering), turns turns, dir = ±1
export function swirl(g, cx, cy, r, turns = 2.2, w = 4, rot = 0, dir = 1) {
  const pts = [], n = Math.ceil(turns * 36);
  for (let i = 0; i <= n; i++) { const u = i / n, a = rot + dir * u * turns * TAU, rr = r * (1 - u * .92); pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]); }
  cutTaper(g, pts, w);
  cut(g, q => { const e = pts[pts.length - 1]; q.arc(e[0], e[1], w * .7, 0, TAU); });
}
// double swirl (the "whorl" on animal joints): one S-shaped double spiral
export function doubleSwirl(g, cx, cy, r, w = 5, rot = 0) {
  const a = [cx + Math.cos(rot) * r * .5, cy + Math.sin(rot) * r * .5], b = [cx - Math.cos(rot) * r * .5, cy - Math.sin(rot) * r * .5];
  swirl(g, a[0], a[1], r * .5, 1.6, w, rot + Math.PI, 1);
  swirl(g, b[0], b[1], r * .5, 1.6, w, rot, 1);
}
// cloud pattern: outline carved line of one main curl + two small curls
export function cloudCut(g, cx, cy, r, w = 3, rot = 0, flip = 1) {
  swirl(g, cx, cy, r, 1.4, w, rot, flip);
  swirl(g, cx + Math.cos(rot + flip * 2.2) * r * 1.25, cy + Math.sin(rot + flip * 2.2) * r * 1.25, r * .55, 1.2, w * .8, rot + Math.PI, -flip);
}
// plum-blossom hole: five petals
export function plum(g, cx, cy, r, rot = -Math.PI / 2) {
  cut(g, q => { for (let k = 0; k < 5; k++) { const a = rot + k * TAU / 5, x = cx + Math.cos(a) * r * .62, y = cy + Math.sin(a) * r * .62; q.moveTo(x + r * .42, y); q.arc(x, y, r * .42, 0, TAU); } });
}
// petal rosette: n teardrop petal holes in a ring (cheek blush / chest rosette)
export function rosette(g, cx, cy, r, n = 6, rot = 0, core = .18) {
  cut(g, q => {
    for (let k = 0; k < n; k++) {
      const a = rot + k * TAU / n, ca = Math.cos(a), sa = Math.sin(a), r0 = r * (core + .08), r1 = r, wd = r * Math.sin(Math.PI / n) * .72;
      const P = (u, v) => [cx + ca * u - sa * v, cy + sa * u + ca * v];
      q.moveTo(...P(r0, 0)); q.quadraticCurveTo(...P((r0 + r1) * .5, wd * 1.25), ...P(r1, 0)); q.quadraticCurveTo(...P((r0 + r1) * .5, -wd * 1.25), ...P(r0, 0)); q.closePath();
    }
  });
  cut(g, q => { q.moveTo(cx + r * core * .55, cy); q.arc(cx, cy, r * core * .55, 0, TAU); });
}
// copper-coin hole: round hole with a square left in the middle
export function coin(g, cx, cy, r) { cut(g, q => { q.arc(cx, cy, r, 0, TAU); q.rect(cx - r * .4, cy - r * .4, r * .8, r * .8); }, 'evenodd'); }
// a row of small round holes
export function dots(g, pts, r) { cut(g, q => { for (const [x, y] of pts) { q.moveTo(x + r, y); q.arc(x, y, r, 0, TAU); } }); }
// parallel carved lines (hair strands, clothing folds): offset hatching along the base curve
export function strands(g, base, n, gap, w, len0 = 0, len1 = 1) {
  for (let k = 0; k < n; k++) {
    const pts = base.map(([x, y], i) => { const a = base[Math.max(0, i - 1)], b = base[Math.min(base.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1; return [x + dy / l * gap * k, y - dx / l * gap * k]; });
    const i0 = Math.floor(pts.length * len0), i1 = Math.ceil(pts.length * len1);
    cutTaper(g, pts.slice(i0, i1), w);
  }
}
// shorthand for a tapered carved line: give control points, smooth, then cut
export function taper(g, pts, w) { cutTaper(g, curve(pts, false, 2), w); }

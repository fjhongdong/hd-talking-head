// Paper-cut letters: take OFL font outlines with opentype.js → flatten to polylines → "re-cut" every letter (rough edges, slight rotation, slight offset)
import { rough, piece, pathPoly, S, g } from './paper.js';
import { hash } from '/core/lib.js';

const FONTS = {};
export async function loadFonts() {
  const load = (u) => new Promise((res, rej) => window.opentype.load(u, (e, f) => e ? rej(e) : res(f)));
  FONTS.gothic = await load('fonts/LeagueGothic.ttf');
}

function flatten(cmds) {
  const contours = []; let cur = null, px = 0, py = 0;
  const seg = 8;
  for (const c of cmds) {
    if (c.type === 'M') { cur = [[c.x, c.y]]; contours.push(cur); px = c.x; py = c.y; }
    else if (c.type === 'L') { cur.push([c.x, c.y]); px = c.x; py = c.y; }
    else if (c.type === 'Q') { for (let i = 1; i <= seg; i++) { const t = i / seg, u = 1 - t; cur.push([u * u * px + 2 * u * t * c.x1 + t * t * c.x, u * u * py + 2 * u * t * c.y1 + t * t * c.y]); } px = c.x; py = c.y; }
    else if (c.type === 'C') { for (let i = 1; i <= seg; i++) { const t = i / seg, u = 1 - t; cur.push([u * u * u * px + 3 * u * u * t * c.x1 + 3 * u * t * t * c.x2 + t * t * t * c.x, u * u * u * py + 3 * u * u * t * c.y1 + 3 * u * t * t * c.y2 + t * t * t * c.y]); } px = c.x; py = c.y; }
  }
  // drop the duplicate closing point
  for (const k of contours) { const a = k[0], b = k[k.length - 1]; if (Math.hypot(a[0] - b[0], a[1] - b[1]) < .01) k.pop(); }
  return contours;
}

// Lay out one line: returns {ch, x, w, polys (local coords, baseline origin), cx} per letter; size = type height (cap height ≈ 0.75*size for League Gothic)
const gcache = new Map();
export function layout(str, size, opt = {}) {
  const f = FONTS[opt.font || 'gothic'];
  const sc = size / f.unitsPerEm, track = (opt.track ?? 0.02) * size;
  let x = 0; const out = [];
  for (let i = 0; i < str.length; i++) {
    const ch = str[i], gl = f.charToGlyph(ch), adv = gl.advanceWidth * sc;
    if (ch !== ' ') {
      const key = (opt.font || 'gothic') + ch + size.toFixed(1);
      let polys = gcache.get(key);
      if (!polys) { polys = flatten(gl.getPath(0, 0, size).commands); gcache.set(key, polys); }
      const bb = gl.getBoundingBox();
      out.push({ ch, x, w: adv, polys, x0: bb.x1 * sc, x1: bb.x2 * sc, top: -bb.y2 * sc, i });
    }
    x += adv + track;
  }
  return { letters: out, width: x - track };
}

// Cut one letter: seed = character + index → a fixed cut edge; jit = strength of the slight rotation/offset
export function cutLetter(L, seed, amp = 1.6) {
  const k = 'cut' + seed + L.ch + L.polys.length + amp;
  let r = gcache.get(k);
  if (!r) { r = L.polys.map((p, j) => rough(p, seed * 7 + j * 13, amp, 9)); gcache.set(k, r); }
  return r;
}

// Draw one line of paper-cut letters (origin = baseline at line start). opt: col, seed, jit (degrees), gap, shadow, each(L, i) → extra transform {dx,dy,rot,s,hide}
export function drawLine(lay, x, y, opt = {}) {
  const col = opt.col || '#000', seed = opt.seed || 1, jit = opt.jit ?? 1;
  for (const L of lay.letters) {
    const e = opt.each ? opt.each(L, L.i) : null; if (e && e.hide) continue;
    const r = (hash(seed * 31 + L.i * 7.3) - .5) * jit * Math.PI / 180 * 2 + (e?.rot || 0);
    const dy = (hash(seed * 11 + L.i * 3.1) - .5) * jit * 3 + (e?.dy || 0);
    const cx = x + L.x + (L.x0 + L.x1) / 2 + (e?.dx || 0), by = y + dy;
    g.save(); g.translate(cx, by); g.rotate(r); if (e?.s) g.scale(e.s, e.s); g.translate(-(L.x0 + L.x1) / 2, 0);
    piece(cutLetter(L, seed + L.i, opt.amp ?? 1.6), e?.col || col, { gap: opt.gap, shadow: opt.shadow, shA: opt.shA });
    g.restore();
  }
}

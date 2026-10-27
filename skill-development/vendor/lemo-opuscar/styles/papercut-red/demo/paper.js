// Red paper-cut engine: paper texture, paper-cut pieces (fill + cut-outs + inner carved lines + cut edges), paper shadows, backlit transmission
// coordinates: each "piece" is drawn in its own unit coordinates (pivot at the origin), pre-rendered to a texture (K pixels/unit) and then placed on the image by a transform.
export const PAL = {
  red: '#d2201f',      // girl / tuanhua / houses (China red)
  nian: '#b00f26',     // Nian beast (one shade darker)
  far: '#7e1424',      // distant hills and houses
  mid: '#9c1323',
  rice: '#f2e8d0',     // off-white rice paper
  indigo: '#1c2446',   // night-colour paper
  gold: '#d9a93f',     // gold leaf
  sub: '#a8111f',      // subtitle paper strip
  back: '#e98f86',     // back of the red paper (shows when folding, one shade lighter)
  shadow: 'rgba(52,6,10,.38)',
  light: '#ffe3a6', transmit: '#e0401c'
};
export function canvas(w, h) { const c = document.createElement('canvas'); c.width = Math.max(1, Math.ceil(w)); c.height = Math.max(1, Math.ceil(h)); return [c, c.getContext('2d')]; }

// ---------- deterministic noise ----------
const h2 = (x, y, s = 0) => { const n = Math.sin(x * 127.1 + y * 311.7 + s * 74.7) * 43758.5453; return n - Math.floor(n); };
function tileNoise(P) {  // value noise with period P
  return (x, y) => {
    const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    const w = (a, b) => h2(((a % P) + P) % P, ((b % P) + P) % P, P);
    return (w(i, j) * (1 - u) + w(i + 1, j) * u) * (1 - v) + (w(i, j + 1) * (1 - u) + w(i + 1, j + 1) * u) * v;
  };
}
export const rnd = (k, s = 0) => h2(k * 1.37 + .5, s * 2.11 + .3, 9.1);

// ---------- paper texture (tileable) ----------
const TEX = {};
function fibers(g, N, n, col, a, len, w, seed) {
  g.save(); g.strokeStyle = col; g.lineWidth = w; g.lineCap = 'round';
  for (let k = 0; k < n; k++) {
    const x = rnd(k, seed) * N, y = rnd(k, seed + 1) * N, an = rnd(k, seed + 2) * 6.283, L = len * (.35 + rnd(k, seed + 3));
    g.globalAlpha = a * (.4 + .6 * rnd(k, seed + 4));
    for (const [ox, oy] of [[0, 0], [-N, 0], [N, 0], [0, -N], [0, N]]) {   // draw twice across the tile boundary
      g.beginPath(); g.moveTo(x + ox, y + oy);
      const bx = Math.cos(an + (rnd(k, seed + 5) - .5)) * L * .5, by = Math.sin(an + (rnd(k, seed + 5) - .5)) * L * .5;
      g.quadraticCurveTo(x + ox + bx, y + oy + by, x + ox + Math.cos(an) * L, y + oy + Math.sin(an) * L); g.stroke();
    }
  }
  g.restore();
}
// neutral grey texture for blending (soft-light: 128 = unchanged), used for the red paper / Nian paper
export function paperGrain(kind = 'red') {
  if (TEX[kind]) return TEX[kind];
  const N = 768, [c, g] = canvas(N, N), id = g.createImageData(N, N), d = id.data;
  const n1 = tileNoise(6), n2 = tileNoise(24), n3 = tileNoise(96);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const f = (n1(x / 128, y / 128) - .5) * 1.0 + (n2(x / 32, y / 32) - .5) * .45 + (n3(x / 8, y / 8) - .5) * .25;
    const sp = h2(x, y, 3) > .993 ? -38 : 0;
    const v = 128 + f * 46 + sp, i = (y * N + x) * 4;
    d[i] = d[i + 1] = d[i + 2] = Math.max(0, Math.min(255, v)); d[i + 3] = 255;
  }
  g.putImageData(id, 0, 0);
  fibers(g, N, 700, '#ffffff', .22, 34, 1.1, 11);
  fibers(g, N, 260, '#000000', .12, 26, .9, 17);
  TEX[kind] = c; return c;
}
// full-colour base paper (rice paper / night paper)
export function paperTile(kind) {
  if (TEX[kind]) return TEX[kind];
  const N = 1024, [c, g] = canvas(N, N), id = g.createImageData(N, N), d = id.data;
  const base = kind === 'rice' ? [242, 232, 208] : kind === 'indigo' ? [28, 36, 70] : kind === 'ink' ? [15, 20, 42] : [240, 226, 196];
  const n1 = tileNoise(4), n2 = tileNoise(16), n3 = tileNoise(128);
  const amp = kind === 'rice' ? .05 : .13;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const f = (n1(x / 256, y / 256) - .5) * 1.2 + (n2(x / 64, y / 64) - .5) * .5 + (n3(x / 8, y / 8) - .5) * .25;
    const k = 1 + f * amp, i = (y * N + x) * 4;
    d[i] = base[0] * k; d[i + 1] = base[1] * k; d[i + 2] = base[2] * (1 + f * amp * 1.1); d[i + 3] = 255;
  }
  g.putImageData(id, 0, 0);
  if (kind === 'rice') { fibers(g, N, 900, '#ffffff', .35, 60, 1.2, 21); fibers(g, N, 500, '#9a8a64', .13, 44, .8, 23); fibers(g, N, 40, '#8a7650', .2, 8, 1.6, 27); }
  else { fibers(g, N, 900, kind === 'ink' ? '#3a4880' : '#5e6ea8', .16, 60, 1.1, 31); fibers(g, N, 400, '#0a0e22', .25, 40, .9, 33); }
  TEX[kind] = c; return c;
}
// fill a rectangle with base paper; the texture moves with the world (C = view transform [k,0,0,k,tx,ty])
export function fillPaper(g, kind, x, y, w, h, C = [1, 0, 0, 1, 0, 0], tint = null) {
  const p = g.createPattern(paperTile(kind), 'repeat');
  p.setTransform(new DOMMatrix([C[0] * .75, 0, 0, C[3] * .75, C[4], C[5]]));
  g.save(); g.fillStyle = p; g.fillRect(x, y, w, h);
  if (tint) { g.fillStyle = tint; g.fillRect(x, y, w, h); }
  g.restore();
}

// ---------- path tools ----------
// smooth closed curve (quadratics through midpoints) → sampled to a polyline, then cut-edge jitter added
export function curve(pts, closed = true, step = 3) {
  const out = [], n = pts.length;
  if (n < 3) return pts.slice();
  const m = (i) => { const a = pts[(i + n) % n], b = pts[(i + 1 + n) % n]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };
  const I = closed ? n : n - 2;
  if (!closed) out.push(pts[0]);
  for (let i = closed ? 0 : 1; i < (closed ? n : n - 1); i++) {
    const s = closed ? m(i - 1) : (i === 1 ? pts[0] : m(i - 1)), c = pts[i], e = closed ? m(i) : (i === n - 2 ? pts[n - 1] : m(i));
    const L = Math.hypot(c[0] - s[0], c[1] - s[1]) + Math.hypot(e[0] - c[0], e[1] - c[1]), k = Math.max(2, Math.ceil(L / step));
    for (let j = 0; j < k; j++) { const u = j / k, a = (1 - u) * (1 - u), b = 2 * u * (1 - u), cc = u * u; out.push([a * s[0] + b * c[0] + cc * e[0], a * s[1] + b * c[1] + cc * e[1]]); }
  }
  if (!closed) out.push(pts[n - 1]);
  return out;
}
export function wob(poly, amp = .35, seed = 1, freq = .09) {   // small irregularity of hand cutting: low-frequency jitter along the arc length
  let s = 0; const out = [];
  for (let i = 0; i < poly.length; i++) {
    if (i) s += Math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1]);
    const a = poly[Math.max(0, i - 1)], b = poly[Math.min(poly.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const x = s * freq, j = Math.floor(x), f = x - j, u = f * f * (3 - 2 * f);
    const nz = (rnd(j, seed) * (1 - u) + rnd(j + 1, seed) * u - .5) * 2 + (rnd(i, seed + 7) - .5) * .35;
    out.push([poly[i][0] - dy / l * nz * amp, poly[i][1] + dx / l * nz * amp]);
  }
  return out;
}
export function trace(g, poly, closed = true) { g.moveTo(poly[0][0], poly[0][1]); for (let i = 1; i < poly.length; i++) g.lineTo(poly[i][0], poly[i][1]); if (closed) g.closePath(); }
export const P = (pts, closed = true, amp = .35, seed = 1) => wob(curve(pts, closed), amp, seed);   // common case: smooth + jitter
export function densify(pts, closed = true, step = 4) {
  const o = [], n = pts.length, m = closed ? n : n - 1;
  for (let i = 0; i < m; i++) { const a = pts[i], b = pts[(i + 1) % n], L = Math.hypot(b[0] - a[0], b[1] - a[1]), k = Math.max(1, Math.ceil(L / step)); for (let j = 0; j < k; j++) o.push([a[0] + (b[0] - a[0]) * j / k, a[1] + (b[1] - a[1]) * j / k]); }
  if (!closed) o.push(pts[n - 1]); return o;
}
export const Pl = (pts, closed = true, amp = .35, seed = 1) => wob(densify(pts, closed), amp, seed);   // sharp-cornered polyline + jitter (architecture)
export function ellipsePoly(cx, cy, rx, ry, rot = 0, n = 40, a0 = 0, a1 = Math.PI * 2) {
  const o = []; for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n, x = Math.cos(a) * rx, y = Math.sin(a) * ry; o.push([cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)]); } return o;
}

// ---------- basic paper-cut operations (in the piece's unit coordinates) ----------
export function fill(g, pathFn, col = PAL.red, rule = 'nonzero') { g.beginPath(); pathFn(g); g.fillStyle = col; g.fill(rule); }
export function cut(g, pathFn, rule = 'nonzero') {   // cut-out: destination-out, set opaque black first (alpha decides how much is removed)
  g.save(); g.globalCompositeOperation = 'destination-out'; g.fillStyle = '#000'; g.beginPath(); pathFn(g); g.fill(rule); g.restore();
}
export function cutLine(g, w, pathFn) {
  g.save(); g.globalCompositeOperation = 'destination-out'; g.strokeStyle = '#000'; g.lineWidth = w; g.lineCap = 'round'; g.lineJoin = 'round';
  g.beginPath(); pathFn(g); g.stroke(); g.restore();
}
// tapered carved line: pointed at both ends (the typical shape of a paper-cut carved line, like half a crescent)
export function cutTaper(g, pts, w, closed = false) {
  const n = pts.length; if (n < 2) return; const L = [], R = [];
  for (let i = 0; i < n; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const k = closed ? 1 : Math.sin(Math.PI * (i / (n - 1))) * .92 + .08, ww = w * k / 2;
    L.push([pts[i][0] - dy / l * ww, pts[i][1] + dx / l * ww]); R.push([pts[i][0] + dy / l * ww, pts[i][1] - dx / l * ww]);
  }
  cut(g, q => { q.moveTo(...L[0]); for (const p of L) q.lineTo(...p); for (let i = n - 1; i >= 0; i--) q.lineTo(...R[i]); q.closePath(); });
}
// inner carved line: cut a slit gap wide at inset inside the outline (double-line outline)
export function inset(g, poly, ins = 4, gap = 1.6, col = PAL.red) {
  g.save(); g.beginPath(); trace(g, poly); g.clip();
  g.globalCompositeOperation = 'destination-out'; g.strokeStyle = '#000'; g.lineJoin = 'round'; g.lineWidth = 2 * (ins + gap); g.beginPath(); trace(g, poly); g.stroke();
  g.globalCompositeOperation = 'source-over'; g.strokeStyle = col; g.lineWidth = 2 * ins; g.beginPath(); trace(g, poly); g.stroke();
  g.restore();
}
// cut inside the poly shape (run fn after clipping)
export function within(g, poly, fn) { g.save(); g.beginPath(); trace(g, poly); g.clip(); fn(); g.restore(); }

// ---------- piece: pre-rendered texture ----------
export const SS = 3;
export function piece(box, draw, opt = {}) {
  const [x0, y0, x1, y1] = box, w = x1 - x0, h = y1 - y0, K = opt.ss || SS;
  const [c, g] = canvas(w * K, h * K);
  g.setTransform(K, 0, 0, K, -x0 * K, -y0 * K); g.lineJoin = 'round'; g.lineCap = 'round';
  draw(g);
  finishPaper(c, g, opt);
  return { c, x0, y0, w, h, K, col: opt.col || PAL.red };
}
// paper feel: soft-light fibre mottling + light / dark cut edges, finally restore the cut-outs with the original alpha
export function finishPaper(c, g, opt = {}) {
  const W = c.width, H = c.height, [m, mg] = canvas(W, H); mg.drawImage(c, 0, 0);
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0);
  if (opt.tex !== false) {
    const pat = g.createPattern(paperGrain(), 'repeat'), s = opt.seed || 0;
    pat.setTransform(new DOMMatrix([opt.texScale || 1, 0, 0, opt.texScale || 1, (s * 137) % 768, (s * 71) % 768]));
    g.globalCompositeOperation = 'soft-light'; g.fillStyle = pat; g.fillRect(0, 0, W, H);
  }
  // cut edge: light edge top-left, dark edge bottom-right (the cut face of the paper, about 1 px)
  const e = opt.edge ?? 1.2;
  if (e > 0) {
    const [r, rg] = canvas(W, H);
    rg.drawImage(m, 0, 0); rg.globalCompositeOperation = 'destination-out'; rg.drawImage(m, e, e);
    rg.globalCompositeOperation = 'source-in'; rg.fillStyle = 'rgba(255,190,170,.55)'; rg.fillRect(0, 0, W, H);
    g.globalCompositeOperation = 'source-atop'; g.drawImage(r, 0, 0);
    rg.globalCompositeOperation = 'source-over'; rg.clearRect(0, 0, W, H);
    rg.drawImage(m, 0, 0); rg.globalCompositeOperation = 'destination-out'; rg.drawImage(m, -e, -e);
    rg.globalCompositeOperation = 'source-in'; rg.fillStyle = 'rgba(60,0,8,.45)'; rg.fillRect(0, 0, W, H);
    g.drawImage(r, 0, 0);
  }
  g.globalCompositeOperation = 'destination-in'; g.drawImage(m, 0, 0);
  g.restore();
}
// place on the image: M = the current world→screen matrix, already on g; the piece's own local transform is set by the caller with setTransform
export function drawPiece(g, p) { g.drawImage(p.c, p.x0, p.y0, p.w, p.h); }
// paper shadow: set the shadow of the current context (device pixels, not affected by the transform); z = sense of how high the paper sits above the base (1 = lying flat)
export function paperShadow(g, zoom = 1, z = 1, col = PAL.shadow) {
  g.shadowColor = col; g.shadowBlur = 5 * zoom * z; g.shadowOffsetX = 2.6 * zoom * z; g.shadowOffsetY = 3.6 * zoom * z;
}
export function noShadow(g) { g.shadowColor = 'rgba(0,0,0,0)'; g.shadowBlur = 0; g.shadowOffsetX = 0; g.shadowOffsetY = 0; }

// ---------- backlit transmission ----------
// build a "transmission texture" for a piece: paper = transmission colour (with thick/thin mottling), cut-outs transparent. Draw it over the light field with multiply: paper = light × transmission, holes = the original light
export function transmitOf(p, col = PAL.transmit, seed = 0) {
  if (p.tr && p.trCol === col) return p.tr;
  const W = p.c.width, H = p.c.height, [c, g] = canvas(W, H);
  g.fillStyle = col; g.fillRect(0, 0, W, H);
  const pat = g.createPattern(paperGrain(), 'repeat'); pat.setTransform(new DOMMatrix([1, 0, 0, 1, (seed * 97) % 768, (seed * 53) % 768]));
  g.globalCompositeOperation = 'overlay'; g.fillStyle = pat; g.fillRect(0, 0, W, H);   // darker where the fibres are thick, brighter where thin
  g.globalCompositeOperation = 'destination-in'; g.drawImage(p.c, 0, 0);
  p.tr = c; p.trCol = col; return c;
}
// only the shape of the "holes" (alpha = 1 - paper), used for projected light and glow: inverted inside box
export function holesOf(p) {
  if (p.holes) return p.holes;
  const W = p.c.width, H = p.c.height, [c, g] = canvas(W, H);
  g.fillStyle = '#fff'; g.fillRect(0, 0, W, H); g.globalCompositeOperation = 'destination-out'; g.drawImage(p.c, 0, 0);
  p.holes = c; return c;
}

// silk.js · screen-print look engine (opaque flat ink layers + hard edges + misregistration + squeegee ink pull + ink-film sheen + paper)
// Every function works under the "current ctx transform": the caller first transforms ctx into paper coordinates (any unit; poster units u are typical).
// The engine handles only "how to print", not "what to print": shapes are supplied by the caller as Path2D or draw functions.

export const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export function mulberry(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
export const hash = n => { n = Math.sin(n * 127.1 + 311.7) * 43758.5453; return n - Math.floor(n); };
export const vnoise = x => { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return lerp(hash(i), hash(i + 1), u); };

// ---------- Colour ----------
export function hex2rgb(h) { h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); const n = parseInt(h, 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
export const rgb2hex = ([r, g, b]) => '#' + [r, g, b].map(v => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');
export const mix = (a, b, t) => { const A = hex2rgb(a), B = hex2rgb(b); return rgb2hex(A.map((v, i) => lerp(v, B[i], t))); };
export const shade = (c, k) => mix(c, k > 0 ? '#ffffff' : '#000000', Math.abs(k));

// ---------- Textures (deterministic, generated once) ----------
function tile(n, fn) { const c = document.createElement('canvas'); c.width = c.height = n; const g = c.getContext('2d'); fn(g, n); return c; }
function noiseField(n, seed, cell) {           // tileable value noise 0..1
  const r = mulberry(seed), gw = Math.ceil(n / cell), grid = [];
  for (let i = 0; i < gw * gw; i++) grid.push(r());
  const at = (x, y) => grid[((y % gw + gw) % gw) * gw + ((x % gw + gw) % gw)];
  const out = new Float32Array(n * n);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const fx = x / cell, fy = y / cell, ix = Math.floor(fx), iy = Math.floor(fy), ux = fx - ix, uy = fy - iy;
    const sx = ux * ux * (3 - 2 * ux), sy = uy * uy * (3 - 2 * uy);
    out[y * n + x] = lerp(lerp(at(ix, iy), at(ix + 1, iy), sx), lerp(at(ix, iy + 1), at(ix + 1, iy + 1), sx), sy);
  }
  return out;
}
export function makeTextures(paperHex, seed = 7) {
  const N = 512, P = hex2rgb(paperHex);
  const n1 = noiseField(N, seed, 64), n2 = noiseField(N, seed + 1, 16), n3 = noiseField(N, seed + 2, 4);
  // paper: cream base + low-frequency mottling + fibres
  const paper = tile(N, (g) => {
    const im = g.createImageData(N, N);
    for (let i = 0; i < N * N; i++) {
      const v = (n1[i] - .5) * 10 + (n2[i] - .5) * 6 + (n3[i] - .5) * 7;
      im.data[i * 4] = P[0] + v; im.data[i * 4 + 1] = P[1] + v; im.data[i * 4 + 2] = P[2] + v * 1.1; im.data[i * 4 + 3] = 255;
    }
    g.putImageData(im, 0, 0);
    const r = mulberry(seed + 9);
    for (let k = 0; k < 900; k++) {           // fibres: short arcs, slightly lighter or darker
      const x = r() * N, y = r() * N, a = r() * Math.PI, l = 3 + r() * 9;
      g.strokeStyle = r() < .5 ? 'rgba(255,255,250,.28)' : 'rgba(120,100,70,.10)'; g.lineWidth = .6 + r() * .5;
      for (const ox of [0, -N, N]) for (const oy of [0, -N, N]) { g.beginPath(); g.moveTo(x + ox, y + oy); g.quadraticCurveTo(x + ox + Math.cos(a) * l * .5 + r() * 2, y + oy + Math.sin(a) * l * .5, x + ox + Math.cos(a) * l, y + oy + Math.sin(a) * l); g.stroke(); }
    }
  });
  // ink mottle (multiply): uneven ink thickness + drag marks along the pull direction (vertical)
  const ns = noiseField(N, seed + 5, 32);
  const mottle = tile(N, (g) => {
    const im = g.createImageData(N, N);
    const colStreak = new Float32Array(N); const r = mulberry(seed + 11);
    for (let x = 0; x < N; x++) colStreak[x] = r() < .06 ? r() : 0;
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const i = y * N + x;
      let v = 255 - (n1[i] * 10 + ns[i] * 8 + n3[i] * 6) - colStreak[x] * 10 * (.5 + .5 * n2[(y * 3 % N) * N + x]);
      im.data[i * 4] = v; im.data[i * 4 + 1] = v; im.data[i * 4 + 2] = v; im.data[i * 4 + 3] = 255;
    }
    g.putImageData(im, 0, 0);
  });
  // pinholes + fine dry-pull scratches (paper colour, source-over): invisible on bare paper, show as paper-white gaps on ink
  const speck = tile(N, (g) => {
    const r = mulberry(seed + 21); g.fillStyle = paperHex;
    for (let k = 0; k < 520; k++) { const x = r() * N, y = r() * N, s = r() < .9 ? .5 + r() * .9 : 1.4 + r() * 1.6; g.globalAlpha = .35 + r() * .5; g.beginPath(); g.ellipse(x, y, s, s * (.6 + r() * .5), r() * 3, 0, 7); g.fill(); }
    g.globalAlpha = .12; g.strokeStyle = paperHex;
    for (let k = 0; k < 40; k++) { const x = r() * N, y = r() * N, l = 20 + r() * 90; g.lineWidth = .4 + r() * .6; g.beginPath(); g.moveTo(x, y); g.lineTo(x + (r() - .5) * 2, y + l); g.stroke(); }
    g.globalAlpha = 1;
  });
  return { paper, mottle, speck, N };
}

// Lay a texture as a pattern in the current coordinate system (texel size = unit)
export function texFill(ctx, tex, x, y, w, h, unit = .6, op = 'source-over', alpha = 1, off = [0, 0]) {
  const p = ctx.createPattern(tex, 'repeat');
  p.setTransform(new DOMMatrix([unit, 0, 0, unit, off[0], off[1]]));
  ctx.save(); ctx.globalCompositeOperation = op; ctx.globalAlpha = alpha; ctx.fillStyle = p; ctx.fillRect(x, y, w, h); ctx.restore();
}
// Paper surface: paper colour + paper grain
export function paperSheet(ctx, T, x, y, w, h, unit = .6) { texFill(ctx, T.paper, x, y, w, h, unit); }
// Post-print finish: ink mottle, pinholes (applied to the whole sheet at once; invisible on paper, visible on ink)
export function inkFinish(ctx, T, x, y, w, h, unit = .6, amt = 1) {
  texFill(ctx, T.mottle, x, y, w, h, unit * 1.4, 'multiply', .55 * amt, [13, 7]);
  texFill(ctx, T.speck, x, y, w, h, unit, 'source-over', .75 * amt, [5, 11]);
}

// ---------- Leading edge of the squeegee pull ----------
// box = [x,y,w,h]; dir = 'down'|'up'|'right'|'left'; p = 0..1 (fraction of the box the leading edge has crossed, including the tail length)
// Returns a Path2D: the area already printed. The leading edge is ragged (streaks where the ink wasn't pulled evenly), length tail (same units as the coordinates).
export function wipeRegion(box, dir, p, seed = 1, tail = 26, step = 5) {
  const [x, y, w, h] = box, path = new Path2D();
  if (p >= 1) { path.rect(x - 4000, y - 4000, w + 8000, h + 8000); return path; }
  if (p <= 0) return path;
  const along = dir === 'down' || dir === 'up' ? h : w, across = dir === 'down' || dir === 'up' ? w : h;
  const front = -tail + p * (along + tail * 2);                // leading edge (along the direction of travel, measured from the box start)
  const pts = [];
  for (let s = -8; s <= across + 8; s += step) {
    const n = hash(Math.floor(s / step) * 7.13 + seed * 31.7), n2 = hash(Math.floor(s / step / 3) * 3.7 + seed);
    const d = front - tail * (n * .65 + n2 * .35);                 // fuller further back
    pts.push([s, d]);
  }
  const P = (a, b) => {                                            // (across, along) → (x,y)
    if (dir === 'down') return [x + a, y + b];
    if (dir === 'up') return [x + a, y + h - b];
    if (dir === 'right') return [x + b, y + a];
    return [x + w - b, y + a];
  };
  const far = -4000;
  let q = P(-8, far); path.moveTo(q[0], q[1]);
  for (const [a, b] of pts) { q = P(a, b); path.lineTo(q[0], q[1]); }
  q = P(across + 8, far); path.lineTo(q[0], q[1]); path.closePath();
  return path;
}
// Current position of the leading edge (along the direction of travel, in coordinates) — used to place the squeegee
export function wipeFront(box, dir, p, tail = 26) {
  const [x, y, w, h] = box, along = dir === 'down' || dir === 'up' ? h : w;
  const f = -tail + p * (along + tail * 2);
  if (dir === 'down') return y + f; if (dir === 'up') return y + h - f; if (dir === 'right') return x + f; return x + w - f;
}

// ---------- One ink layer ----------
// part = { path: Path2D, knock?: Path2D(knockout), paint?: (ctx)=>void(custom fill, e.g. text), rule?: 'nonzero'|'evenodd' }
// o = { color, reg:[dx,dy](misregistration), clip?: Path2D(ink-pull leading edge), sheen:0..1(ink-film edge highlight), trap:0..1(overprint trap edge), alpha }
export function ink(ctx, part, o) {
  if (o.alpha === 0) return;
  ctx.save();
  if (o.clip) ctx.clip(o.clip);
  const [dx, dy] = o.reg || [0, 0];
  ctx.translate(dx, dy);
  if (o.alpha != null && o.alpha < 1) ctx.globalAlpha = o.alpha;
  ctx.fillStyle = o.color;
  if (o.trap && !part.paint) {          // trap edge: lightly print the same stencil a second time (slightly offset, multiply), leaving a dark edge on the colour below
    let g = part.path; if (part.knock) { g = new Path2D(); g.addPath(part.path); g.addPath(part.knock); }
    ctx.save(); ctx.translate(o.trapOff?.[0] ?? 2.2, o.trapOff?.[1] ?? -1.6); ctx.globalCompositeOperation = 'multiply'; ctx.globalAlpha = (o.alpha ?? 1) * .45 * o.trap;
    ctx.fill(g, part.knock ? 'evenodd' : (part.rule || 'nonzero')); ctx.restore();
  }
  if (part.paint) { part.paint(ctx, o.color); ctx.restore(); return; }
  let p = part.path;
  if (part.knock) { p = new Path2D(); p.addPath(part.path); p.addPath(part.knock); }
  ctx.fill(p, part.knock ? 'evenodd' : (part.rule || 'nonzero'));
  const rule = part.knock ? 'evenodd' : (part.rule || 'nonzero');
  const lw = o.lw || 1.6;
  if (o.sheen) {                        // ink thickness: done with fills only (no lines inside the union) — a light edge along the top-left, a dark edge along the bottom-right
    ctx.save(); ctx.clip(p, rule);
    ctx.globalAlpha = (o.alpha ?? 1) * .22 * o.sheen; ctx.fillStyle = '#ffffff'; ctx.fill(p, rule);
    ctx.globalAlpha = 1; ctx.fillStyle = o.color; ctx.translate(lw, lw); ctx.fill(p, rule);
    ctx.translate(-lw * 2, -lw * 2); ctx.globalAlpha = .14 * o.sheen; ctx.fillStyle = '#000'; ctx.globalCompositeOperation = 'source-atop';
    ctx.restore();
    ctx.save(); ctx.clip(p, rule); ctx.translate(-lw * .8, -lw * .8);
    const inv = new Path2D(); inv.rect(-1e5, -1e5, 2e5, 2e5); inv.addPath(p);
    ctx.globalAlpha = .12 * o.sheen; ctx.fillStyle = '#000'; ctx.fill(inv, 'evenodd');
    ctx.restore();
  }
  ctx.restore();
}

// ---------- Squeegee ----------
// Draw the squeegee on the line (a→b) (top view), lead = unit vector of the direction of travel; beads=[{t0,t1,color}] ink beads segmented along the blade (split fountain)
// o: { scale, seed, roll(ink-bead rolling phase, changes over time), handle(0..1 how much of the handle shows), shadow, blade, wood }
export function squeegee(ctx, a, b, lead, o = {}) {
  const beads = o.beads || [{ t0: 0, t1: 1, color: o.color || '#333' }];
  const ux = b[0] - a[0], uy = b[1] - a[1], L = Math.hypot(ux, uy), tx = ux / L, ty = uy / L;
  const nx = lead[0], ny = lead[1], s = o.scale || 1, roll = o.roll || 0, hd = o.handle ?? 1, sd = o.seed || 0;
  const pt = (t, d) => [a[0] + tx * L * t + nx * d * s, a[1] + ty * L * t + ny * d * s];
  const poly = (list, fill) => { ctx.beginPath(); list.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fillStyle = fill; ctx.fill(); };
  const ext = 18 / L, back = -30 * hd;
  // drop shadow
  ctx.save(); ctx.globalAlpha = o.shadow ?? .2; ctx.translate(-nx * 6 * s + 8 * s, -ny * 6 * s + 10 * s);
  poly([pt(-ext, back - 4), pt(1 + ext, back - 4), pt(1 + ext, 6), pt(-ext, 6)], '#000'); ctx.restore();
  // ink bead: a round, full line of wet ink in front of the blade (thick round-capped line), dark along the lower edge with a continuous highlight along the upper edge; bright spots on the highlight roll along the blade with roll
  const W0 = o.bead || 24;
  const wAt = (t) => W0 * (.82 + .18 * Math.sin(t * 9 + sd) + .08 * Math.sin(t * 31 + sd * 2));
  for (const bd of beads) {
    const n = Math.max(12, Math.ceil((bd.t1 - bd.t0) * L / 6));
    const up = [], dn = [];
    for (let i = 0; i <= n; i++) { const t = lerp(bd.t0, bd.t1, i / n); up.push(pt(t, 3)); dn.push(pt(t, 3 + wAt(t))); }
    // round off both ends
    ctx.beginPath(); up.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    for (let i = dn.length - 1; i >= 0; i--) ctx.lineTo(dn[i][0], dn[i][1]);
    ctx.closePath();
    ctx.save(); ctx.translate(5 * s, 7 * s); ctx.globalAlpha = .22; ctx.fillStyle = '#000'; ctx.fill(); ctx.restore();   // shadow of the ink bead on the mesh
    ctx.fillStyle = bd.color; ctx.fill();
    // volume: the lit half brighter, the shadow side darker (three flat bands)
    ctx.fillStyle = mix(bd.color, '#ffffff', .22);
    ctx.beginPath(); for (let i = 0; i <= n; i++) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) * .12); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); }
    for (let i = n; i >= 0; i--) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) * .5); ctx.lineTo(p[0], p[1]); } ctx.closePath(); ctx.fill();
    ctx.fillStyle = mix(bd.color, '#000000', .18);
    ctx.beginPath(); for (let i = 0; i <= n; i++) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) * .72); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); }
    for (let i = n; i >= 0; i--) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) - .5); ctx.lineTo(p[0], p[1]); } ctx.closePath(); ctx.fill();
    ctx.save(); ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    // dark leading edge (ink thickness)
    ctx.strokeStyle = mix(bd.color, '#000000', .28); ctx.lineWidth = 3.2 * s;
    ctx.beginPath(); for (let i = 0; i <= n; i++) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) - 1.4); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); } ctx.stroke();
    // highlight (one continuous streak + rolling bright spots)
    ctx.strokeStyle = 'rgba(255,255,255,.42)'; ctx.lineWidth = 2.4 * s;
    ctx.beginPath(); for (let i = 0; i <= n; i++) { const t = lerp(bd.t0, bd.t1, i / n), p = pt(t, 3 + wAt(t) * .32); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); } ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,.75)';
    const span = (bd.t1 - bd.t0) * L, gap = 46;
    for (let q = ((roll * 60) % gap + gap) % gap; q < span; q += gap) {
      const t = bd.t0 + q / L, p = pt(t, 3 + wAt(t) * .3), r = (2.2 + 1.2 * hash(Math.floor(q / gap) + sd)) * s;
      ctx.beginPath(); ctx.ellipse(p[0], p[1], r * 1.8, r, Math.atan2(ty, tx), 0, 7); ctx.fill();
    }
    // sticky strings: short thick ink threads pulled out of the bead's front (wide at the root, thin at the end, with a small drop hanging)
    ctx.fillStyle = bd.color;
    const ns = Math.max(1, Math.round(span / 70));
    for (let k = 0; k < ns; k++) {
      const h = hash(k * 7.3 + sd), t = lerp(bd.t0, bd.t1, (k + .25 + .5 * h) / ns);
      const len = 5 + 7 * (.5 + .5 * Math.sin(roll * .9 + k * 2.1 + sd)), w0 = 4.5, base = 3 + wAt(t) - 3;
      const q = (dt, d) => pt(t + dt * s / L, d);
      const P0 = q(-w0, base), P1 = q(w0, base), P2 = q(.8, base + len), P3 = q(-.8, base + len);
      ctx.beginPath(); ctx.moveTo(P0[0], P0[1]); ctx.quadraticCurveTo(...q(-1.2, base + len * .45), P3[0], P3[1]); ctx.lineTo(P2[0], P2[1]); ctx.quadraticCurveTo(...q(1.2, base + len * .45), P1[0], P1[1]); ctx.closePath(); ctx.fill();
      const D = q(0, base + len + 1.4); ctx.beginPath(); ctx.arc(D[0], D[1], 2.2 * s, 0, 7); ctx.fill();
    }
    ctx.restore();
  }
  // rubber blade
  poly([pt(-ext * .6, -2), pt(1 + ext * .6, -2), pt(1 + ext * .6, 4), pt(-ext * .6, 4)], o.blade || '#23201E');
  poly([pt(-ext * .6, 2.2), pt(1 + ext * .6, 2.2), pt(1 + ext * .6, 4), pt(-ext * .6, 4)], '#57524C');
  // wooden handle (can show only a section)
  if (hd > 0) {
    poly([pt(-ext, back), pt(1 + ext, back), pt(1 + ext, -2), pt(-ext, -2)], o.wood || '#C48A52');
    poly([pt(-ext, back), pt(1 + ext, back), pt(1 + ext, back + 5 * hd), pt(-ext, back + 5 * hd)], '#D9A56C');
    ctx.save(); ctx.strokeStyle = 'rgba(90,50,20,.35)'; ctx.lineWidth = 1.1 * s;
    for (let k = 0; k < 5; k++) { const d = back + 6 + k * (-back - 8) / 5; ctx.beginPath(); for (let i = 0; i <= 30; i++) { const t = -ext + (1 + 2 * ext) * i / 30; const p = pt(t, d + Math.sin(t * 9 + k * 2) * 1.2); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); } ctx.stroke(); }
    ctx.restore();
    // metal end caps at both ends of the handle
    for (const t of [-ext, 1 + ext - 6 / L]) poly([pt(t, back), pt(t + 6 / L, back), pt(t + 6 / L, -2), pt(t, -2)], '#9A958B');
  }
}

// ---------- Screen (top view): aluminium frame + mesh; lift 0..1 raises it (compresses toward the hinge side and casts a shadow) ----------
// flood: the "image waiting to print" visible on the screen (mesh openings ahead of the squeegee already filled by the flood stroke): (ctx)=>void
export function screenFrame(ctx, box, o = {}) {
  const [x, y, w, h] = box, lift = o.lift || 0, fw = o.frame || 34;
  ctx.save();
  // lift: hinged on the top edge, compressed vertically (an approximation in top view), and casts a shadow
  const k = 1 - .55 * lift, sh = 26 * lift + 6;
  ctx.translate(0, y); ctx.scale(1, k); ctx.translate(0, -y);
  ctx.save(); ctx.globalAlpha = .22 + .1 * lift; ctx.fillStyle = '#000';
  const shp = new Path2D(); shp.rect(x + sh * .6, y + sh, w, h); shp.rect(x + sh * .6 + fw, y + sh + fw, w - fw * 2, h - fw * 2);
  ctx.fill(shp, 'evenodd');
  if (lift > 0) { ctx.globalAlpha = .12 * lift; ctx.fillRect(x + sh * .6 + fw, y + sh + fw, w - fw * 2, h - fw * 2); }
  ctx.restore();
  // mesh
  ctx.save(); ctx.beginPath(); ctx.rect(x + fw, y + fw, w - fw * 2, h - fw * 2); ctx.clip();
  ctx.fillStyle = o.mesh || 'rgba(236,214,128,.20)'; ctx.fillRect(x, y, w, h);
  if (o.flood) { ctx.save(); ctx.globalAlpha = .42; o.flood(ctx); ctx.restore(); }
  if (o.meshLines !== false) {
    ctx.strokeStyle = o.meshLine || 'rgba(120,100,40,.07)'; ctx.lineWidth = .35; const st = o.meshStep || 6;
    ctx.beginPath();
    for (let xx = x + fw; xx < x + w - fw; xx += st) { ctx.moveTo(xx, y); ctx.lineTo(xx, y + h); }
    for (let yy = y + fw; yy < y + h - fw; yy += st) { ctx.moveTo(x, yy); ctx.lineTo(x + w, yy); }
    ctx.stroke();
  }
  // emulsion (non-printing areas are a translucent blue-green film)
  if (o.emulsion) { ctx.save(); ctx.globalAlpha = o.emulsionAlpha ?? .16; ctx.fillStyle = '#2E6F78'; ctx.fill(o.emulsion, 'evenodd'); ctx.restore(); }
  ctx.restore();
  // aluminium frame (two flat colours)
  const fr = new Path2D(); fr.rect(x, y, w, h); fr.rect(x + fw, y + fw, w - fw * 2, h - fw * 2);
  ctx.fillStyle = o.frameColor || '#B7B2A6'; ctx.fill(fr, 'evenodd');
  const inner = new Path2D(); inner.rect(x + fw - 6, y + fw - 6, w - fw * 2 + 12, h - fw * 2 + 12); inner.rect(x + fw, y + fw, w - fw * 2, h - fw * 2);
  ctx.fillStyle = '#8E897E'; ctx.fill(inner, 'evenodd');
  ctx.fillStyle = '#D6D1C4'; ctx.fillRect(x, y, w, 5);
  // tape (blue blockout tape along the inner edge of the frame)
  ctx.fillStyle = o.tape || '#3C6E9E';
  ctx.fillRect(x + fw, y + fw, w - fw * 2, 10); ctx.fillRect(x + fw, y + h - fw - 10, w - fw * 2, 10);
  ctx.fillRect(x + fw, y + fw, 10, h - fw * 2); ctx.fillRect(x + w - fw - 10, y + fw, 10, h - fw * 2);
  ctx.restore();
}

// ---------- General shape helpers (any shape can be handed to ink() for printing) ----------
export function polyPath(pts, close = true) { const p = new Path2D(); pts.forEach((q, i) => i ? p.lineTo(q[0], q[1]) : p.moveTo(q[0], q[1])); if (close) p.closePath(); return p; }
export function circlePath(x, y, r) { const p = new Path2D(); p.arc(x, y, r, 0, Math.PI * 2); return p; }
export function ringPath(x, y, r0, r1) { const p = new Path2D(); p.arc(x, y, r1, 0, Math.PI * 2); p.moveTo(x + r0, y); p.arc(x, y, r0, 0, Math.PI * 2, true); return p; }
export function rectPath(x, y, w, h) { const p = new Path2D(); p.rect(x, y, w, h); return p; }
export function unionPath(list) { const p = new Path2D(); for (const q of list) p.addPath(q); return p; }
// Midpoint-displacement ridge line: endpoints a,b, returns a point list (deterministic)
export function ridgeLine(a, b, rough, depth, seed) {
  let pts = [a, b]; const r = mulberry(seed);
  for (let d = 0; d < depth; d++) {
    const n = [pts[0]];
    for (let i = 0; i < pts.length - 1; i++) { const p = pts[i], q = pts[i + 1]; n.push([(p[0] + q[0]) / 2 + (r() - .5) * rough * .2, (p[1] + q[1]) / 2 + (r() - .5) * rough]); n.push(q); }
    pts = n; rough *= .52;
  }
  return pts;
}
// Stepped colour bands: horizontal stripes between [y0,y1] going from colorA to colorB (stripe width from thick to thin) — returns the Path2D for colour B (printed over A)
export function bandSteps(x, w, y0, y1, n = 5, curve = 0) {
  const p = new Path2D(), H = y1 - y0;
  // stripe i: thinner the further down it is
  let yy = y0;
  for (let i = 0; i < n; i++) {
    const cell = H / n, th = cell * (1 - (i + .5) / n) * .95 + 1.2;
    const top = y0 + cell * i, bot = top + th;
    p.moveTo(x, top);
    for (let k = 0; k <= 24; k++) { const xx = x + w * k / 24; p.lineTo(xx, top + curve * Math.sin(k / 24 * Math.PI)); }
    for (let k = 24; k >= 0; k--) { const xx = x + w * k / 24; p.lineTo(xx, bot + curve * Math.sin(k / 24 * Math.PI)); }
    p.closePath(); yy = bot;
  }
  return p;
}

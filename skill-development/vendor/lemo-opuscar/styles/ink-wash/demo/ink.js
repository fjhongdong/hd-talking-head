// Ink-wash brush stroke engine (Canvas2D)
// One stroke = centreline + pressure profile + a number of "bristles". A wet brush's ink body is drawn into the wet canvas (the compositor bleeds it and pools ink at its edges),
// a dry brush's bristles are drawn into the dry canvas (broken up according to ink load → feibai (飞白, dry-brush streaks)). All coordinates are world units; the caller sets setTransform.
import { clamp, lerp, mulberry, hash, vnoise } from '/core/lib.js';

export const TONE = { jiao: .96, nong: .82, zhong: .6, dan: .34, qing: .16 }; // the five ink tones jiao, nong, zhong, dan, qing (焦浓重淡清: scorched-black, dark, heavy, pale, clear)

// Catmull-Rom densify → resample at equal arc length
function densify(P, per = 8) {
  if (P.length < 3) {
    const out = []; const [a, b] = [P[0], P[P.length - 1]];
    for (let i = 0; i <= per; i++) { const t = i / per; out.push([lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2] ?? 1, b[2] ?? 1, t)]); }
    return out;
  }
  const out = [];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
    for (let k = 0; k < per; k++) {
      const t = k / per, t2 = t * t, t3 = t2 * t;
      const f = (a, b, c, d) => .5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      out.push([f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1]), lerp(p1[2] ?? 1, p2[2] ?? 1, t)]);
    }
  }
  const l = P[P.length - 1]; out.push([l[0], l[1], l[2] ?? 1]);
  return out;
}
function resample(D, ds) {
  const acc = [0];
  for (let i = 1; i < D.length; i++) acc.push(acc[i - 1] + Math.hypot(D[i][0] - D[i - 1][0], D[i][1] - D[i - 1][1]));
  const L = acc[acc.length - 1] || 1e-6, n = Math.max(2, Math.min(600, Math.ceil(L / ds) + 1)), out = [];
  let j = 0;
  for (let i = 0; i < n; i++) {
    const s = L * i / (n - 1);
    while (j < D.length - 2 && acc[j + 1] < s) j++;
    const u = clamp((s - acc[j]) / ((acc[j + 1] - acc[j]) || 1e-6));
    out.push([lerp(D[j][0], D[j + 1][0], u), lerp(D[j][1], D[j + 1][1], u), lerp(D[j][2], D[j + 1][2], u)]);
  }
  return { pts: out, len: L };
}

// Pressure profiles
const PROF = {
  brush: s => Math.min(1, .45 + s / .1 * .55) * Math.pow(1 - s * .9, .45),          // press-and-pause start, gradual taper
  even: s => Math.min(1, .55 + s / .05 * .45) * Math.min(1, .5 + (1 - s) / .06 * .5),
  tip: s => Math.pow(Math.sin(Math.PI * clamp(s * .96 + .02)), .6),                  // pointed at both ends
  lens: s => Math.pow(Math.sin(Math.PI * clamp(s)), .75),
  nail: s => Math.pow(1 - s, .7) * Math.min(1, .7 + s * 6),                          // heavy start, exits with a sharp tip
  na: s => (.25 + .75 * Math.pow(clamp(s / .82), 1.4)) * (s > .82 ? Math.pow(1 - (s - .82) / .18, .6) : 1), // na (捺, right-falling press stroke): light to heavy, exits flat
  press: s => Math.min(1, .3 + s / .15 * .7) * Math.min(1, (1 - s) / .12 * .8 + .2),
  fan: s => (.4 + .6 * Math.pow(s, .8)) * Math.min(1, (1 - s) / .06 * .6 + .4) * Math.min(1, s / .05 * .5 + .5),
  robe: s => (.75 + .25 * s) * Math.min(1, s / .05 * .5 + .5) * Math.min(1, (1 - s) / .08 * .7 + .3),
  rise: s => Math.min(1, .12 + s / .14 * .88) * Math.min(1, (1 - s) / .08 * .7 + .3),
  cone: s => Math.pow(1 - s, .55) * Math.min(1, s / .04 * .6 + .4),
  dot: s => Math.pow(Math.sin(Math.PI * clamp(s * .9 + .05)), .45),
};

let SEED = 1;
export function reseed(s) { SEED = s | 0; }

// Build one stroke
// pts: [[x,y,(p)]]，o: {w, tone, dry, wet, prof, rough, nb, seed, ds, fade}
export function mk(pts, o = {}) {
  const w = o.w ?? 4, seed = o.seed ?? (SEED = (SEED * 16807) % 2147483647);
  const ds = o.ds ?? Math.max(.25, w * .18);
  const { pts: P, len } = resample(densify(pts, o.per ?? 10), ds);
  const n = P.length, prof = typeof o.prof === 'function' ? o.prof : PROF[o.prof || 'brush'];
  const rough = o.rough ?? .12, ws = [], nx = [], ny = [];
  for (let i = 0; i < n; i++) {
    const s = i / (n - 1);
    ws.push(Math.max(w * .04, w * prof(s) * P[i][2] * (1 + rough * (vnoise(seed * .013 + (o.boil || 0) * .35 + s * (o.gapLen ?? len) / (w * 1.3 + 1)) * 2 - 1))));
    const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
    nx.push(-dy / L); ny.push(dx / L);
  }
  const dry = o.dry ?? .25;
  let side = o.side || 0;
  if (o.darkDir) {  // decide the dark side automatically: the side of the stroke whose mean normal points toward darkDir
    let ax = 0, ay = 0; for (let i = 0; i < n; i++) { ax += nx[i]; ay += ny[i]; }
    side = (Math.abs(o.side || 1)) * Math.sign(ax * o.darkDir[0] + ay * o.darkDir[1] || 1);
  }
  const nb = o.nb ?? Math.round(clamp(w * 1.1, 4, 56));
  const R = mulberry(seed);
  const br = [];
  for (let j = 0; j < nb; j++) {
    const off = (j + .5) / nb - .5 + (R() - .5) * .6 / nb;
    const edge = Math.abs(off) * 2;                          // 0 centre → 1 edge
    br.push({
      off, bw: w / nb * (1.0 + R() * 1.1), a: .55 + R() * .45, ph: R() * 1000,
      load: 1 - dry * (.15 + .85 * edge) * (.5 + R() * .7),  // bristles at the edge carry less ink
      gs: .5 + R() * 1.6,                                    // scale of the ink breaks
      end: 1 - R() * dry * .35,
    });
  }
  return { P, n, len, ws, nx, ny, w, tone: o.tone ?? TONE.nong, dry, wet: o.wet ?? 0, br, seed, fade: o.fade ?? dry * .55, bodyK: o.body ?? 1, brK: o.bristle ?? 1, color: o.color || null, side, brWet: !!o.brWet, solid: !!o.solid, gapLen: o.gapLen ?? null };
}

// Draw one stroke. L = {wet, dry} two 2D contexts; p = how far to draw (0..1); am = overall opacity
export function draw(L, s, p = 1, am = 1) {
  if (p <= 0 || am <= 0) return;
  p = clamp(p);
  const { P, n, ws, nx, ny } = s, m = (n - 1) * p, k = Math.floor(m), f = m - k;
  const cnt = f > .001 && k < n - 1 ? k + 2 : k + 1;
  const X = i => i <= k ? P[i][0] : lerp(P[k][0], P[k + 1][0], f), Y = i => i <= k ? P[i][1] : lerp(P[k][1], P[k + 1][1], f);
  const CC = s.color ? s.color.join(',') : '0,0,0';
  const WW = i => ws[Math.min(i, n - 1)] * (p < 1 && i >= cnt - 2 ? .75 : 1);
  // Ink body
  const bodyA = s.tone * Math.pow(1 - s.dry, 1.6) * s.bodyK * am;
  if (bodyA > .004) {
    const path = new Path2D();
    for (let i = 0; i < cnt; i++) { const j = Math.min(i, n - 1), hw = WW(i) / 2; const x = X(i) + nx[j] * hw, y = Y(i) + ny[j] * hw; i ? path.lineTo(x, y) : path.moveTo(x, y); }
    for (let i = cnt - 1; i >= 0; i--) { const j = Math.min(i, n - 1), hw = WW(i) / 2; path.lineTo(X(i) - nx[j] * hw, Y(i) - ny[j] * hw); }
    path.closePath();
    // ink load decreases along the stroke direction (more visible with a dry brush)
    const g = (c, a) => {
      if (a <= .003) return;
      const gr = c.createLinearGradient(P[0][0], P[0][1], P[n - 1][0], P[n - 1][1]);
      gr.addColorStop(0, `rgba(${CC},${clamp(a)})`); gr.addColorStop(1, `rgba(${CC},${clamp(a * (1 - s.fade))})`);
      c.fillStyle = gr; c.fill(path);
    };
    if (s.color) { if (L.col) g(L.col, bodyA); }
    else {
      if (s.solid) { if (L.dry) g(L.dry, bodyA * .92); if (L.wet && s.wet > 0) g(L.wet, bodyA * s.wet); }
      else {
        if (s.wet > 0 && L.wet) g(L.wet, bodyA * s.wet);
        if (s.wet < 1 && L.dry) g(L.dry, bodyA * (1 - s.wet) * .8);
      }
    }
  }
  // Bristles (feibai)
  const c = s.color ? L.col : (s.brWet ? L.wet : L.dry); if (!c || s.brK <= 0) return;
  const brA = s.tone * am * s.brK * (s.brWet ? 1 : (s.wet > .6 ? .12 : 1));
  c.lineCap = 'round'; c.lineJoin = 'round'; c.strokeStyle = `rgb(${CC})`;
  const dsl = (s.gapLen ?? s.len) / (n - 1);
  for (const b of s.br) {
    const e = Math.min(m, (n - 1) * b.end), kk = Math.floor(e); if (kk < 1) continue;
    const lat = s.side ? lerp(1 - Math.abs(s.side), 1, clamp(b.off * Math.sign(s.side) * 1.6 + .5)) : 1;
    c.globalAlpha = clamp(brA * b.a * lat);
    c.lineWidth = b.bw;
    c.beginPath(); let on = false;
    const gsc = Math.max(6, s.w * 1.4) * b.gs;
    for (let i = 0; i <= kk; i++) {
      const u = i / (n - 1), sl = i * dsl;
      // Ink load: falls with stroke progress, faster for a dry brush; noise decides where it breaks
      const ink = b.load - s.dry * (.08 + 1.15 * Math.pow(u, 1.25));
      const v = ink + (vnoise(b.ph + sl / gsc) - .5) * .9 * s.dry + (vnoise(b.ph * 1.7 + sl / (gsc * .18)) - .5) * .25 * s.dry;
      if (v > .42 * s.dry + .02) {
        const hw = ws[i] * (b.off + (vnoise(b.ph * 3 + sl / (gsc * 2)) - .5) * .07), x = P[i][0] + nx[i] * hw, y = P[i][1] + ny[i] * hw;
        on ? c.lineTo(x, y) : c.moveTo(x, y); on = true;
      } else on = false;
    }
    c.stroke();
  }
  c.globalAlpha = 1;
}

// Draw a group of strokes in order (writing order), p ∈ [0,1]
export function drawSeq(L, S, p = 1, am = 1, overlap = .15) {
  const N = S.length; if (!N) return;
  if (p >= 1) { for (const s of S) draw(L, s, 1, am); return; }
  // allocate time by length
  const tot = S.reduce((a, s) => a + s.len + 20, 0); let acc = 0;
  for (const s of S) {
    const t0 = acc / tot, t1 = (acc + s.len + 20) / tot; acc += s.len + 20;
    draw(L, s, (p - t0) / ((t1 - t0) * (1 + overlap)), am);
  }
}

// Ink dot (diantai 点苔 moss dots, spattered ink): a small flattened elliptical blob
export function blot(c, x, y, r, a, rot = 0, sq = 1, seed = 0) {
  if (a <= .003 || r <= .05) return;
  c.save(); c.translate(x, y); c.rotate(rot); c.scale(1, sq);
  c.globalAlpha = clamp(a); c.fillStyle = '#000';
  c.beginPath();
  const N = 18, ph = seed * 7.13 + x * .01;
  for (let i = 0; i <= N; i++) {
    const t = i / N * Math.PI * 2, rr = r * (.78 + .44 * vnoise(ph + i * .9) + .12 * Math.sin(t * 3 + ph));
    i ? c.lineTo(Math.cos(t) * rr, Math.sin(t) * rr) : c.moveTo(Math.cos(t) * rr, Math.sin(t) * rr);
  }
  c.fill();
  c.restore(); c.globalAlpha = 1;
}

// Ink mass: polygon of wet ink (bamboo hat, distant mountains, robe base colour). Edges subdivided + noise jitter; can take a linear gradient g = [x0,y0,x1,y1,a0,a1]
export function mass(c, poly, a, jit = 0, seed = 0, g = null) {
  if (a <= .003) return;
  const pts = [];
  const N = poly.length;
  for (let i = 0; i < N; i++) {
    const p = poly[i], q = poly[(i + 1) % N], L = Math.hypot(q[0] - p[0], q[1] - p[1]);
    const k = jit ? Math.max(1, Math.min(24, Math.round(L / Math.max(2, jit * 2.5)))) : 1;
    const nx = -(q[1] - p[1]) / (L || 1), ny = (q[0] - p[0]) / (L || 1);
    for (let j = 0; j < k; j++) {
      const u = j / k, d = jit ? (vnoise(seed * 3.1 + i * 5.3 + u * k * .8) - .5) * jit * 2 : 0;
      pts.push([lerp(p[0], q[0], u) + nx * d, lerp(p[1], q[1], u) + ny * d]);
    }
  }
  c.globalAlpha = 1;
  if (g) { const gr = c.createLinearGradient(g[0], g[1], g[2], g[3]); gr.addColorStop(0, `rgba(0,0,0,${clamp(a * g[4])})`); gr.addColorStop(1, `rgba(0,0,0,${clamp(a * g[5])})`); c.fillStyle = gr; }
  else { c.fillStyle = `rgba(0,0,0,${clamp(a)})`; }
  c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])); c.closePath(); c.fill();
}

// Utility: list of points on a quadratic Bézier
export function qpts(x0, y0, cx, cy, x1, y1, n = 8, p0 = 1, p1 = 1) {
  const out = [];
  for (let i = 0; i <= n; i++) { const t = i / n, u = 1 - t; out.push([u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1, lerp(p0, p1, t)]); }
  return out;
}
export { hash, vnoise };

// Engine: palettes, utilities, grid patterns in the style of the official core graphic, athlete skeleton, typography
// Everything hangs off window.G. Canvas is 1920×1080.
(function () {
  const W = 1920, H = 1080;
  const G = (window.G = { W, H });

  // ───────── Maths / easing ─────────
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const inv = (a, b, x) => clamp((x - a) / (b - a));
  const E = {
    lin: (t) => t,
    io: (t) => 0.5 - 0.5 * Math.cos(Math.PI * clamp(t)),
    o2: (t) => 1 - (1 - t) * (1 - t),
    o3: (t) => 1 - Math.pow(1 - clamp(t), 3),
    i3: (t) => Math.pow(clamp(t), 3),
    io3: (t) => (t = clamp(t), t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    oExp: (t) => (t = clamp(t), t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
    iExp: (t) => (t = clamp(t), t <= 0 ? 0 : Math.pow(2, 10 * t - 10)),
    ioExp: (t) => (t = clamp(t), t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2),
    oBack: (t, s = 1.4) => (t = clamp(t) - 1, t * t * ((s + 1) * t + s) + 1),
    o5: (t) => 1 - Math.pow(1 - clamp(t), 5),
  };
  const rng = (seed) => {
    let a = seed >>> 0;
    return () => {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  };
  const D2R = Math.PI / 180;
  Object.assign(G, { clamp, lerp, inv, E, rng, D2R });

  // ───────── Colour ─────────
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  const toHex = (c) => '#' + c.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');
  const mix = (a, b, t) => { const A = hex(a), B = hex(b); return toHex(A.map((v, i) => lerp(v, B[i], t))); };
  const rgba = (h, a) => { const c = hex(h); return `rgba(${c[0]},${c[1]},${c[2]},${a})`; };
  G.mix = mix; G.rgba = rgba;

  const CREAM = '#fbf6ec', INK = '#15111c';
  // Each palette: t0 darkest → t4 lightest (sampled from the official core-graphic artwork), fg foreground (text + figure), fg2 secondary text
  const PAL = {
    red:    { name: 'Jonetsu Red',        t: ['#c21d15', '#d22419', '#e83220', '#ec5a26', '#f07a45'], fg: CREAM, dim: '#f6c7ae', deep: '#8e150f' },
    purple: { name: 'Kakitsubata Purple', t: ['#231a6e', '#2c2084', '#4e3a93', '#644d9d', '#7a62a9'], fg: CREAM, dim: '#c9bde6', deep: '#170f4c' },
    green:  { name: 'Shinrin Green',      t: ['#006d35', '#008440', '#079a3e', '#2da547', '#68b15d'], fg: CREAM, dim: '#c3e6c4', deep: '#004d25' },
    gold:   { name: 'Kinshachi Gold',     t: ['#b48900', '#c69b00', '#d5b102', '#debc2f', '#e7d16c'], fg: '#211904', dim: '#6d5500', deep: '#8a6a00' },
    ochre:  { name: 'Dento Ocher',        t: ['#946a2e', '#ac7d38', '#c18e46', '#d2a55c', '#e0bf84'], fg: '#1e1409', dim: '#5e4221', deep: '#6e4d1f' },
    ink:    { name: 'Sumi',               t: ['#0f0c15', '#16121d', '#1e1a27', '#2a2535', '#3a3447'], fg: CREAM, dim: '#9a93a8', deep: '#08060b', accent: '#d5b102' },
  };
  for (const k in PAL) { PAL[k].key = k; PAL[k].base = PAL[k].t[2]; }
  PAL.multi = PAL.purple; // Chapter 7 rotates palettes per card; this is only a placeholder
  G.PAL = PAL; G.CREAM = CREAM; G.INK = INK;
  G.CYCLE = ['red', 'purple', 'green', 'gold', 'ochre'];

  // ───────── Canvas utilities ─────────
  G.canvas = (w = W, h = H) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
  G.disc = (ctx, x, y, r, col) => { if (r <= 0) return; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); };
  G.seg = (ctx, a, b, w, col) => { ctx.strokeStyle = col; ctx.lineWidth = w; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); };
  G.ring = (ctx, x, y, r, w, col) => { ctx.strokeStyle = col; ctx.lineWidth = w; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); };
  G.poly = (ctx, pts, col) => { ctx.fillStyle = col; ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); ctx.closePath(); ctx.fill(); };

  // ───────── Grid pattern (the language of the official core graphic) ─────────
  // Large circles / half circles spanning several cells form the base; small cells carry motifs (scales, stripes, triangles, concentric arcs, sun discs…),
  // and finally whole rows are cut and offset — this is the most recognisable feature of the core graphic.
  const CELL = 180;
  G.CELL = CELL;

  function motif(ctx, kind, x, y, s, c, r) {
    const [a, b, cc, d] = c; // background, main shape, secondary shape, accent
    ctx.save();
    ctx.beginPath(); ctx.rect(x, y, s, s); ctx.clip();
    ctx.fillStyle = a; ctx.fillRect(x, y, s, s);
    const rot = Math.floor(r() * 4);
    ctx.translate(x + s / 2, y + s / 2); ctx.rotate(rot * Math.PI / 2); ctx.translate(-s / 2, -s / 2);
    switch (kind) {
      case 0: // quarter circle
        G.disc(ctx, 0, 0, s, b); break;
      case 1: // half circle
        G.disc(ctx, s / 2, s, s / 2, b); break;
      case 2: // circle + small circle
        G.disc(ctx, s / 2, s / 2, s / 2, b); G.disc(ctx, s * 0.62, s * 0.42, s * 0.13, cc); break;
      case 3: { // striped half circle (setting sun)
        ctx.save(); ctx.beginPath(); ctx.arc(s / 2, s, s / 2, Math.PI, 0); ctx.clip();
        for (let i = 0; i < 7; i++) { ctx.fillStyle = i % 2 ? b : cc; ctx.fillRect(0, s / 2 + i * s / 14, s, s / 14); }
        ctx.restore(); break;
      }
      case 4: { // seigaiha (青海波, overlapping wave-scale pattern)
        const k = s / 4;
        for (let row = 0; row < 5; row++) for (let i = -1; i < 5; i++) {
          const cx = i * k + (row % 2 ? k / 2 : 0), cy = row * k * 0.5 + k * 0.5;
          G.disc(ctx, cx, cy, k * 0.5, row % 2 ? b : cc);
          G.disc(ctx, cx, cy, k * 0.3, a);
        }
        break;
      }
      case 5: { // dot scales
        G.disc(ctx, s / 2, s / 2, s / 2, b);
        ctx.save(); ctx.beginPath(); ctx.arc(s / 2, s / 2, s / 2, 0, Math.PI * 2); ctx.clip();
        const k = s / 6;
        for (let j = 0; j < 7; j++) for (let i = 0; i < 7; i++) G.disc(ctx, i * k + (j % 2 ? k / 2 : 0), j * k, k * 0.36, cc);
        ctx.restore(); break;
      }
      case 6: { // triangle scales (三角鳞文, uroko pattern)
        const k = s / 5;
        for (let j = 0; j < 3; j++) for (let i = 0; i < 6; i++) {
          const ox = i * k + (j % 2 ? k / 2 : 0) - k / 2, oy = s * 0.35 + j * k * 0.8;
          G.poly(ctx, [[ox, oy + k * 0.8], [ox + k / 2, oy], [ox + k, oy + k * 0.8]], j % 2 ? b : cc);
        }
        break;
      }
      case 7: // concentric arcs
        for (let i = 5; i >= 1; i--) G.disc(ctx, 0, s, (s * i) / 5, i % 2 ? b : a);
        break;
      case 8: { // sun disc / gear
        const R = s * 0.3;
        ctx.fillStyle = b; ctx.beginPath();
        for (let i = 0; i < 16; i++) { const t0 = (i / 16) * Math.PI * 2; ctx.moveTo(s / 2, s / 2); ctx.arc(s / 2, s / 2, R * 1.35, t0, t0 + Math.PI / 32); }
        ctx.fill();
        G.disc(ctx, s / 2, s / 2, R, b); G.disc(ctx, s / 2, s / 2, R * 0.55, cc);
        break;
      }
      case 9: { // checks
        G.disc(ctx, s, s, s * 0.9, b);
        const k = s / 7;
        for (let j = 0; j < 7; j++) for (let i = 0; i < 7; i++) if ((i + j) % 2 === 0) { ctx.fillStyle = cc; ctx.fillRect(i * k + k * 0.2, j * k + k * 0.2, k * 0.6, k * 0.6); }
        break;
      }
      case 10: // crescent
        G.disc(ctx, s / 2, s / 2, s * 0.46, b); G.disc(ctx, s * 0.66, s * 0.38, s * 0.4, a); break;
      case 11: // S wave
        G.disc(ctx, 0, s / 2, s / 2, b); G.disc(ctx, s, s / 2, s / 2, cc); break;
      case 12: { // gradient quarter circle (the sense of light in the official graphic)
        const g = ctx.createLinearGradient(0, 0, s, s); g.addColorStop(0, cc); g.addColorStop(1, b);
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(0, s); ctx.arc(0, s, s, -Math.PI / 2, 0); ctx.closePath(); ctx.fill();
        break;
      }
      case 13: { // horizontal bars fading out
        for (let i = 0; i < 9; i++) { ctx.globalAlpha = 1 - i / 10; ctx.fillStyle = b; ctx.fillRect(0, s * 0.1 + i * s * 0.09, s * (1 - i * 0.06), s * 0.045); }
        ctx.globalAlpha = 1; break;
      }
    }
    ctx.restore();
  }
  G.motif = motif;

  // Build one pattern canvas (2 cells wider than the screen, so whole rows can be offset)
  const patCache = new Map();
  G.pattern = function (palKey, seed = 1, o = {}) {
    const spread = o.spread ?? 1; // 1 = the contrast of the official artwork; smaller is softer
    const density = o.density ?? 0.5; // share of cells that get small motifs
    const key = palKey + '|' + seed + '|' + spread + '|' + density + '|' + (o.cell || CELL);
    if (patCache.has(key)) { const v = patCache.get(key); patCache.delete(key); patCache.set(key, v); return v; }
    if (patCache.size > 10) patCache.delete(patCache.keys().next().value);
    const S = o.cell || CELL;
    const P = PAL[palKey];
    const base = P.t[2];
    const T = P.t.map((c) => mix(base, c, spread));
    const cols = Math.ceil(W / S) + 3, rows = Math.ceil(H / S) + 1;
    const cv = G.canvas(cols * S, rows * S), ctx = cv.getContext('2d');
    const r = rng(seed * 7919 + 13);
    ctx.fillStyle = T[1]; ctx.fillRect(0, 0, cv.width, cv.height);
    // Large shapes: circles / half circles on a 2×2 macro grid
    for (let j = -1; j < rows; j += 1) for (let i = -1; i < cols; i += 1) {
      const k = r();
      const cx = i * S, cy = j * S;
      if (k < 0.34) G.disc(ctx, cx + S, cy + S, S, T[Math.floor(r() * 4)]);
      else if (k < 0.5) { G.disc(ctx, cx + S, cy + S, S, T[3]); G.disc(ctx, cx + S, cy + S, S * 0.5, T[0]); }
    }
    for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
      if (r() > density) continue;
      const pick = () => T[Math.floor(r() * 5)];
      let a = pick(), b = pick(); while (b === a) b = pick();
      let cc = pick(); while (cc === b) cc = pick();
      motif(ctx, Math.floor(r() * 14), i * S, j * S, S, [a, b, cc, T[4]], r);
    }
    patCache.set(key, cv);
    return cv;
  };

  // Draw the pattern with whole-row offsets. offs(row) returns the pixel offset.
  G.drawPattern = function (ctx, pat, offs, o = {}) {
    const S = o.cell || CELL;
    const rows = Math.ceil(H / S);
    const oy = o.oy || 0;
    for (let j = 0; j < rows + 1; j++) {
      const dx = clamp(offs ? offs(j) : 0, -S, S);
      const y = j * S + oy;
      if (y > H || y + S < 0) continue;
      ctx.drawImage(pat, 0, j * S, pat.width, S, -S + dx, y, pat.width, S + 0.5);
    }
  };

  // ───────── Athlete skeleton (geometric pictogram) ─────────
  // Units: height ≈ 1. Origin = hips. Faces +x.
  // Angles: rot = whole body (positive = flipping forward / clockwise), torso = upper-body forward lean, head = nod;
  // limbs a*/l* are measured as "straight down = 0°, forward = 90°, overhead = 180°, backward = negative";
  // arms are in the torso's frame, legs in the whole-body frame; forearm / shin values are absolute angles in that same frame.
  // R = near side (light), L = far side (dark).
  const LEN = { torso: 0.3, neck: 0.045, head: 0.082, ua: 0.16, fa: 0.15, th: 0.225, sh: 0.225 };
  const WID = { torso: 0.145, arm: 0.076, leg: 0.094 };
  G.LEN = LEN; G.WID = WID;
  const dirDown = (deg, frame) => { const a = (deg + 0) * D2R; const v = [Math.sin(a), Math.cos(a)]; return rot2(v, frame); };
  const rot2 = (v, deg) => { const a = deg * D2R, c = Math.cos(a), s = Math.sin(a); return [v[0] * c - v[1] * s, v[0] * s + v[1] * c]; };
  const add = (p, v, k) => [p[0] + v[0] * k, p[1] + v[1] * k];
  G.rot2 = rot2;

  const DEF = { x: 0, y: 0, rot: 0, torso: 0, head: 0, aL1: -8, aL2: -4, aR1: 8, aR2: 12, lL1: -4, lL2: -4, lR1: 4, lR2: 4 };
  G.POSE_DEFAULT = DEF;
  G.joints = function (p) {
    p = Object.assign({}, DEF, p);
    const hip = [p.x, p.y];
    const tf = p.rot + p.torso;
    const up = rot2([0, -1], tf);
    const neck = add(hip, up, LEN.torso);
    const sho = add(hip, up, LEN.torso - 0.025);
    const hup = rot2(up, p.head);
    const head = add(neck, hup, LEN.neck + LEN.head);
    const arm = (a1, a2) => { const e = add(sho, dirDown(a1, tf), LEN.ua); const h = add(e, dirDown(a2, tf), LEN.fa); return [sho, e, h]; };
    const leg = (l1, l2) => { const k = add(hip, dirDown(l1, p.rot), LEN.th); const f = add(k, dirDown(l2, p.rot), LEN.sh); return [hip, k, f]; };
    return { p, hip, neck, sho, head, up, aL: arm(p.aL1, p.aL2), aR: arm(p.aR1, p.aR2), lL: leg(p.lL1, p.lL2), lR: leg(p.lR1, p.lR2) };
  };

  // Draw the figure. col = near-side colour, far = far-side colour. Under the current ctx transform (unit = body height).
  G.drawFigure = function (ctx, J, col, far) {
    const limb = (L, w, c) => { G.seg(ctx, L[0], L[1], w, c); G.seg(ctx, L[1], L[2], w * 0.92, c); };
    limb(J.lL, WID.leg, far); limb(J.aL, WID.arm, far);
    G.seg(ctx, J.hip, add(J.neck, J.up, -0.02), WID.torso, col);
    limb(J.lR, WID.leg, col); limb(J.aR, WID.arm, col);
    G.disc(ctx, J.head[0], J.head[1], LEN.head, col);
  };

  // Interpolate between two poses (angles linearly)
  G.lerpPose = function (a, b, t) {
    const o = {};
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) {
      const va = a[k] ?? DEF[k] ?? 0, vb = b[k] ?? DEF[k] ?? 0;
      o[k] = typeof va === 'number' ? lerp(va, vb, t) : (t < 0.5 ? va : vb);
    }
    return o;
  };
  // Keyframes: keys = [{b: beat, ...pose, e: 'easing'}], loop = loop length (beats)
  G.keyPose = function (keys, u, loop) {
    if (loop) u = ((u % loop) + loop) % loop;
    if (u <= keys[0].b) return keys[0];
    for (let i = 0; i < keys.length - 1; i++) {
      const a = keys[i], b = keys[i + 1];
      if (u < b.b) return G.lerpPose(a, b, (E[b.e || 'io'])((u - a.b) / (b.b - a.b)));
    }
    const last = keys[keys.length - 1];
    if (loop) { const a = last, b = keys[0]; return G.lerpPose(a, b, (E[b.e || 'io'])((u - a.b) / (loop - a.b + b.b))); }
    return last;
  };
  // Run cycle: ph = phase (cycles), k = intensity 0..1
  G.runCycle = function (ph, k = 1, o = {}) {
    const s = Math.sin(ph * Math.PI * 2), c = Math.cos(ph * Math.PI * 2);
    const sw = 55 * k, lean = o.lean ?? 12 * k;
    const legR = s * sw, legL = -s * sw;
    const knee = (l, cc) => l - (20 + 70 * k * Math.max(0, -cc) + 25 * k * (l < 0 ? 1 : 0.3));
    return {
      torso: lean, rot: 0, y: -Math.abs(c) * 0.03 * k,
      lR1: legR, lR2: knee(legR, c), lL1: legL, lL2: knee(legL, -c),
      aR1: -s * 60 * k, aR2: -s * 60 * k + 85, aL1: s * 60 * k, aL2: s * 60 * k + 85,
    };
  };
  G.walkCycle = function (ph, k = 1) {
    const s = Math.sin(ph * Math.PI * 2);
    return { torso: 4, y: -Math.abs(Math.cos(ph * Math.PI * 2)) * 0.012, lR1: s * 28, lR2: s * 28 - 6, lL1: -s * 28, lL2: -s * 28 - 6, aR1: -s * 32, aR2: -s * 32 + 70, aL1: s * 32, aL2: s * 32 + 70 };
  };

  // ───────── Text ─────────
  G.F = {
    en: (w, px) => `${w} ${px}px "Inter Tight"`,
    zh: (w, px) => `${w} ${px}px "Noto Sans SC"`,
    jp: (w, px) => `${w} ${px}px "Noto Sans JP"`,
    mono: (px, w = 500) => `${w} ${px}px "DM Mono"`,
  };
  // Auto-fit font size: no wider than maxW
  G.fitFont = function (ctx, text, fam, weight, px, maxW, ls = 0) {
    ctx.font = G.F[fam](weight, px);
    ctx.letterSpacing = ls ? ls * px + 'px' : '0px';
    const w = ctx.measureText(text).width;
    return w > maxW ? Math.floor(px * maxW / w) : px;
  };
  // Mask slide-up entrance: p 0→1
  G.maskText = function (ctx, text, x, y, font, col, p, o = {}) {
    ctx.save();
    ctx.font = font; ctx.letterSpacing = o.ls || '0px'; ctx.textAlign = o.align || 'left'; ctx.textBaseline = 'alphabetic';
    const m = ctx.measureText(text);
    const asc = o.asc ?? m.actualBoundingBoxAscent, desc = o.desc ?? m.actualBoundingBoxDescent;
    const h = asc + desc;
    ctx.beginPath();
    const w = m.width + 40;
    const x0 = o.align === 'center' ? x - w / 2 : o.align === 'right' ? x - w : x - 20;
    ctx.rect(x0, y - asc - 6, w, h + 12);
    ctx.clip();
    const dy = (1 - (o.ease || E.oExp)(p)) * (h + 16) * (o.dir || 1);
    ctx.fillStyle = col;
    ctx.fillText(text, x, y + dy);
    ctx.restore();
    return m.width;
  };
  // Typewriter (monospaced meta info)
  G.typeText = function (ctx, text, x, y, font, col, p, o = {}) {
    const n = Math.floor(text.length * clamp(p) + 0.001);
    ctx.save(); ctx.font = font; ctx.letterSpacing = o.ls || '0px'; ctx.fillStyle = col; ctx.textAlign = o.align || 'left';
    ctx.fillText(text.slice(0, n), x, y);
    if (p > 0 && p < 1 && o.caret !== false) { const w = ctx.measureText(text.slice(0, n)).width; ctx.fillRect(x + w + 4, y - 18, 11, 22); }
    ctx.restore();
  };
  G.hair = (ctx, x, y, w, col, p = 1, lw = 2) => { ctx.fillStyle = col; ctx.fillRect(x, y, w * clamp(p), lw); };
})();

// engine.js — Dark Tech Keynote drawing engine (reusable: scenes only call functions from here)
// Dark near-black gradient ground + thin-line grid + soft light + rounded UI panels + a single accent colour; light-sweep reveal, scrambled rolling digits, snap flight, strip perspective, 2.5D camera.
import { clamp, lerp, seg, ss, eo, ei, eio, back, spring, mulberry, hash, TAU } from '../../../core/lib.js';
export { clamp, lerp, seg, ss, eo, ei, eio, back, spring, mulberry, hash, TAU };

export const W = 1920, H = 1080;
export const PAL = {
  bg0: '#0A0B0F', bg1: '#151822', surf: '#12151C', surf2: '#1A1E28', surf3: '#222734',
  line: 'rgba(255,255,255,.08)', hi: 'rgba(255,255,255,.10)',
  text: '#E8EAF0', dim: '#8A90A0', mute: '#5C6272',
  accent: '#B7F34A', red: '#FF5A5F', cool: '#3B4CCA',
};
export const FONT = { ui: 'Inter', disp: 'InterTight', mono: 'JBMono' };
/** Swap the brand accent colour (the only colour). Example: setAccent('#D97757') */
export function setAccent(hex) { PAL.accent = hex; }
export const font = (px, wt = 500, fam = 'ui') => `${wt} ${px}px ${FONT[fam] || fam}`;
export function rgba(hex, a) {
  if (hex.startsWith('rgba')) return hex;
  const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
}
export function mix(h1, h2, t) {
  const a = parseInt(h1.slice(1), 16), b = parseInt(h2.slice(1), 16);
  const c = s => Math.round(lerp(a >> s & 255, b >> s & 255, t));
  return `rgb(${c(16)},${c(8)},${c(0)})`;
}

// ───────────────────────── Canvas tools ─────────────────────────
const _pool = {};
/** Get an offscreen canvas (reused by name) */
export function buf(name, w = W, h = H) {
  let c = _pool[name];
  if (!c || c.width !== w || c.height !== h) { c = _pool[name] = document.createElement('canvas'); c.width = w; c.height = h; }
  const g = c.getContext('2d'); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none';
  return [c, g];
}
export function rr(g, x, y, w, h, r) { g.beginPath(); g.roundRect(x, y, w, h, Math.max(0, Math.min(r, w / 2, h / 2))); }

// ───────────────────────── Background / grid / glow ─────────────────────────
/** Near-black gradient ground + cool light patch + vignette. o.lift brightens the top, o.cool cool-light strength, o.dark overall darkening 0..1 */
export function bg(g, o = {}) {
  const { lift = 1, cool = 1, dark = 0, cx = W * 0.5, cy = H * 0.34 } = o;
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0);
  g.fillStyle = PAL.bg0; g.fillRect(0, 0, W, H);
  let gr = g.createRadialGradient(cx, cy, 0, cx, cy, W * 0.75);
  gr.addColorStop(0, rgba(PAL.bg1, 0.95 * lift)); gr.addColorStop(1, rgba(PAL.bg0, 0));
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
  if (cool > 0) glow(g, W * 0.78, H * 0.12, 900, PAL.cool, 0.08 * cool);
  if (dark > 0) { g.fillStyle = `rgba(4,5,7,${dark})`; g.fillRect(0, 0, W, H); }
  g.restore();
}
/** Soft radial glow */
export function glow(g, x, y, r, color, a) {
  if (a <= 0 || r <= 0) return;
  const gr = g.createRadialGradient(x, y, 0, x, y, r);
  gr.addColorStop(0, rgba(color, a)); gr.addColorStop(0.45, rgba(color, a * 0.35)); gr.addColorStop(1, rgba(color, 0));
  g.fillStyle = gr; g.fillRect(x - r, y - r, r * 2, r * 2);
}
/** Thin-line grid: screen space, ox/oy/scale make it follow the camera. module in world units */
export function grid(g, o = {}) {
  const { ox = 0, oy = 0, scale = 1, module = 48, alpha = 1, major = 4, rect = [0, 0, W, H], color = '255,255,255' } = o;
  const step = module * scale; if (step < 4 || alpha <= 0) return;
  const [rx, ry, rw, rh] = rect;
  g.save(); g.beginPath(); g.rect(rx, ry, rw, rh); g.clip(); g.lineWidth = 1;
  const i0 = Math.floor((rx - ox) / step), i1 = Math.ceil((rx + rw - ox) / step);
  const j0 = Math.floor((ry - oy) / step), j1 = Math.ceil((ry + rh - oy) / step);
  for (let pass = 0; pass < 2; pass++) {
    g.strokeStyle = `rgba(${color},${(pass ? 0.06 : 0.032) * alpha})`; g.beginPath();
    for (let i = i0; i <= i1; i++) { if ((i % major === 0) !== !!pass) continue; const x = Math.round(ox + i * step) + 0.5; g.moveTo(x, ry); g.lineTo(x, ry + rh); }
    for (let j = j0; j <= j1; j++) { if ((j % major === 0) !== !!pass) continue; const y = Math.round(oy + j * step) + 0.5; g.moveTo(rx, y); g.lineTo(rx + rw, y); }
    g.stroke();
  }
  g.restore();
}
export function vignette(g, a = 0.55) {
  const gr = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 1.05);
  gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, `rgba(0,0,0,${a})`);
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
}

// ───────────────────────── Panels / arbitrary shapes ─────────────────────────
/** Rounded UI panel: soft shadow + top-lit gradient + 1px stroke + inner highlight on the top edge. o.cheap uses a cheap shadow (for large numbers of elements) */
export function panel(g, x, y, w, h, o = {}) {
  const { r = 14, fill = PAL.surf, fill2 = null, stroke = PAL.line, shadow = 1, cheap = false, hi = 1, alpha = 1 } = o;
  g.save(); g.globalAlpha *= alpha;
  if (shadow > 0) {
    if (cheap) { g.fillStyle = `rgba(0,0,0,${0.35 * shadow})`; rr(g, x + 2, y + h * 0.06 + 4, w, h, r); g.fill(); }
    else { g.shadowColor = `rgba(0,0,0,${0.55 * shadow})`; g.shadowBlur = Math.min(90, 18 + h * 0.18); g.shadowOffsetY = Math.min(40, 6 + h * 0.06); g.fillStyle = fill; rr(g, x, y, w, h, r); g.fill(); g.shadowColor = 'transparent'; }
  }
  const gr = g.createLinearGradient(0, y, 0, y + h);
  gr.addColorStop(0, fill2 || mix(fill.startsWith('#') ? fill : '#12151C', '#2A3040', 0.25)); gr.addColorStop(Math.min(1, 60 / Math.max(h, 1)), fill); gr.addColorStop(1, fill);
  g.fillStyle = gr; rr(g, x, y, w, h, r); g.fill();
  g.lineWidth = 1; g.strokeStyle = stroke; rr(g, x + 0.5, y + 0.5, w - 1, h - 1, r); g.stroke();
  if (hi > 0) { g.strokeStyle = `rgba(255,255,255,${0.07 * hi})`; g.beginPath(); g.moveTo(x + r, y + 1.5); g.lineTo(x + w - r, y + 1.5); g.stroke(); }
  g.restore();
}
/**
 * Draw any shape (Path2D) in this style: outer glow + top-lit gradient fill + 1px edge light + optional light-sweep highlight.
 * o.accent=true → solid glowing accent colour ("the only colour"); o.color sets another colour; o.sweep 0..1 light-band position; o.glow glow radius
 */
export function litShape(g, path, o = {}) {
  const { accent = false, color = null, glowR = accent ? 28 : 0, alpha = 1, sweep = null, bbox = [0, 0, W, H], stroke = true } = o;
  const [bx, by, bw, bh] = bbox; const c = color || (accent ? PAL.accent : null);
  g.save(); g.globalAlpha *= alpha;
  if (c) {
    if (glowR > 0) { g.shadowColor = rgba(c, 0.75); g.shadowBlur = glowR; }
    g.fillStyle = c; g.fill(path); g.shadowColor = 'transparent';
    const gr = g.createLinearGradient(0, by, 0, by + bh); gr.addColorStop(0, 'rgba(255,255,255,.28)'); gr.addColorStop(0.5, 'rgba(255,255,255,0)');
    g.fillStyle = gr; g.fill(path);
  } else {
    g.shadowColor = 'rgba(0,0,0,.5)'; g.shadowBlur = 40; g.shadowOffsetY = 14;
    const gr = g.createLinearGradient(0, by, 0, by + bh); gr.addColorStop(0, '#262B38'); gr.addColorStop(0.35, PAL.surf2); gr.addColorStop(1, PAL.surf);
    g.fillStyle = gr; g.fill(path); g.shadowColor = 'transparent';
  }
  if (stroke) { g.lineWidth = 1; g.strokeStyle = c ? rgba('#ffffff', 0.35) : 'rgba(255,255,255,.12)'; g.stroke(path); }
  if (sweep != null) {
    g.save(); g.clip(path);
    const d = Math.hypot(bw, bh), sx = bx - d * 0.3 + sweep * d * 1.6;
    const gr = g.createLinearGradient(sx - 120, by, sx + 120, by + bh * 0.4);
    gr.addColorStop(0, 'rgba(255,255,255,0)'); gr.addColorStop(0.5, 'rgba(255,255,255,.22)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
    g.globalCompositeOperation = 'lighter'; g.fillStyle = gr; g.fillRect(bx, by, bw, bh); g.restore();
  }
  g.restore();
}
/** Four-point sparkle (four-pointed star) path: r outer radius, k waist pinch 0..1 */
export function sparklePath(cx, cy, r, k = 0.18, rot = 0) {
  const p = new Path2D();
  for (let i = 0; i < 4; i++) {
    const a = rot + i * TAU / 4, b = a + TAU / 8, a2 = a + TAU / 4;
    const P = [cx + Math.cos(a) * r, cy + Math.sin(a) * r], Q = [cx + Math.cos(a2) * r, cy + Math.sin(a2) * r];
    const C = [cx + Math.cos(b) * r * k, cy + Math.sin(b) * r * k];
    if (i === 0) p.moveTo(...P);
    p.quadraticCurveTo(C[0], C[1], Q[0], Q[1]);
  }
  p.closePath(); return p;
}
/** Caret trail: draws a fading light band along a series of points, optionally ending in a caret. pts=[[x,y],...] oldest to newest */
export function trail(g, pts, o = {}) {
  const { color = PAL.accent, width = 6, alpha = 1, caretH = 0 } = o;
  if (pts.length < 2) return;
  g.save(); g.lineCap = 'butt'; g.lineJoin = 'round';
  for (let i = 1; i < pts.length; i++) {
    const u = i / (pts.length - 1);
    g.strokeStyle = rgba(color, alpha * u * u * 0.9); g.lineWidth = width * (0.25 + 0.75 * u);
    g.shadowColor = rgba(color, 0.6 * u * alpha); g.shadowBlur = 18 * u;
    g.beginPath(); g.moveTo(...pts[i - 1]); g.lineTo(...pts[i]); g.stroke();
  }
  g.restore();
  if (caretH > 0) { const [x, y] = pts[pts.length - 1]; caret(g, x, y, caretH, { color, alpha }); }
}

// ───────────────────────── Caret / brand ─────────────────────────
/** Caret: centre anchor. o.sx/o.sy squash and stretch, o.on brightness (blink), o.glow glow multiplier */
export function caret(g, x, y, h, o = {}) {
  const { sx = 1, sy = 1, on = 1, glow: gl = 1, color = PAL.accent, alpha = 1, wr = 1 / 14 } = o;
  if (on <= 0.001 || alpha <= 0) return;
  const w = Math.max(2, h * wr) * sx, hh = h * sy;
  g.save(); g.globalAlpha *= alpha * on;
  if (gl > 0) { glow(g, x, y, hh * 0.9 * gl, color, 0.22 * gl); g.shadowColor = rgba(color, 0.9); g.shadowBlur = hh * 0.22 * gl; }
  g.fillStyle = color; rr(g, x - w / 2, y - hh / 2, w, hh, Math.min(w / 2, 4 + h * 0.01)); g.fill();
  g.shadowColor = 'transparent'; g.restore();
}
/** Tidy logo: rounded square + one accent-colour caret */
export function tidyMark(g, x, y, s, o = {}) {
  const { alpha = 1, on = 1 } = o;
  g.save(); g.globalAlpha *= alpha;
  panel(g, x - s / 2, y - s / 2, s, s, { r: s * 0.28, fill: PAL.surf3, shadow: 0.6 });
  caret(g, x, y, s * 0.52, { on, glow: 0.6, wr: 1 / 6.5 });
  g.restore();
}
/** Wordmark "Tidy" + caret, (x,y) is the baseline start; returns the width */
export function wordmark(g, x, y, px, o = {}) {
  const { alpha = 1, on = 1, color = PAL.text } = o;
  g.save(); g.globalAlpha *= alpha; g.font = font(px, 600); g.fillStyle = color; g.textBaseline = 'alphabetic';
  if (g.letterSpacing !== undefined) g.letterSpacing = `${-0.03 * px}px`;
  g.fillText('Tidy', x, y); const w = g.measureText('Tidy').width;
  if (g.letterSpacing !== undefined) g.letterSpacing = '0px';
  caret(g, x + w + px * 0.14, y - px * 0.36, px * 0.86, { on, wr: 1 / 11 });
  g.restore(); return w + px * 0.2;
}

// ───────────────────────── UI elements (material for the chaos section) ─────────────────────────
const APPS = [
  { c: '#5B7CFA', g: 'bubble' }, { c: '#8C6CF0', g: 'cal' }, { c: '#2FB6A6', g: 'bell' }, { c: '#E0A33A', g: 'star' },
  { c: '#4C9BE8', g: 'mail' }, { c: '#D0668A', g: 'heart' }, { c: '#6E7890', g: 'gear' },
];
export function appIcon(g, x, y, s, k) {
  const a = APPS[((k % APPS.length) + APPS.length) % APPS.length];
  const gr = g.createLinearGradient(0, y, 0, y + s); gr.addColorStop(0, mix(a.c, '#ffffff', 0.15)); gr.addColorStop(1, mix(a.c, '#000000', 0.25));
  g.fillStyle = gr; rr(g, x, y, s, s, s * 0.26); g.fill();
  g.strokeStyle = 'rgba(255,255,255,.92)'; g.fillStyle = 'rgba(255,255,255,.92)'; g.lineWidth = Math.max(1, s * 0.08); g.lineCap = 'round';
  const cx = x + s / 2, cy = y + s / 2, u = s * 0.22;
  g.beginPath();
  switch (a.g) {
    case 'bubble': g.ellipse(cx, cy - u * 0.1, u * 1.2, u * 0.9, 0, 0, TAU); g.fill(); break;
    case 'cal': g.rect(cx - u, cy - u * 0.8, u * 2, u * 1.8); g.stroke(); g.beginPath(); g.moveTo(cx - u, cy - u * 0.2); g.lineTo(cx + u, cy - u * 0.2); g.stroke(); break;
    case 'bell': g.arc(cx, cy, u, Math.PI, 0); g.lineTo(cx + u * 1.2, cy + u * 0.7); g.lineTo(cx - u * 1.2, cy + u * 0.7); g.closePath(); g.fill(); break;
    case 'star': for (let i = 0; i < 10; i++) { const r = i % 2 ? u * 0.5 : u * 1.2, an = -Math.PI / 2 + i * Math.PI / 5; g.lineTo(cx + Math.cos(an) * r, cy + Math.sin(an) * r); } g.closePath(); g.fill(); break;
    case 'mail': g.rect(cx - u * 1.2, cy - u * 0.8, u * 2.4, u * 1.6); g.moveTo(cx - u * 1.2, cy - u * 0.8); g.lineTo(cx, cy + u * 0.1); g.lineTo(cx + u * 1.2, cy - u * 0.8); g.stroke(); break;
    case 'heart': g.moveTo(cx, cy + u); g.bezierCurveTo(cx - u * 2, cy - u * 0.2, cx - u * 0.6, cy - u * 1.5, cx, cy - u * 0.4); g.bezierCurveTo(cx + u * 0.6, cy - u * 1.5, cx + u * 2, cy - u * 0.2, cx, cy + u); g.fill(); break;
    default: g.arc(cx, cy, u, 0, TAU); g.stroke(); g.beginPath(); g.arc(cx, cy, u * 0.35, 0, TAU); g.fill();
  }
}
/** Red count badge (centre anchor) */
export function badge(g, x, y, text, s = 1) {
  g.save(); g.font = font(13 * s, 700); const w = Math.max(20 * s, g.measureText(text).width + 12 * s), h = 20 * s;
  g.fillStyle = PAL.red; g.shadowColor = rgba(PAL.red, 0.5); g.shadowBlur = 8 * s; rr(g, x - w / 2, y - h / 2, w, h, h / 2); g.fill(); g.shadowColor = 'transparent';
  g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, x, y + 0.5 * s); g.restore();
}
/** Notification card (top-left anchor) */
export function notif(g, x, y, w, h, o = {}) {
  const { app = 0, title = 'Reminder', body = 'You have 3 unread messages', time = 'now', cheap = true, badge: bd = null, alpha = 1 } = o;
  g.save(); g.globalAlpha *= alpha;
  panel(g, x, y, w, h, { r: h * 0.24, fill: '#1A1E28', cheap, shadow: 1 });
  const s = h * 0.46; appIcon(g, x + h * 0.22, y + (h - s) / 2, s, app);
  const tx = x + h * 0.22 + s + h * 0.18;
  g.textBaseline = 'alphabetic'; g.fillStyle = PAL.text; g.font = font(h * 0.2, 600); g.fillText(title, tx, y + h * 0.42);
  g.fillStyle = PAL.dim; g.font = font(h * 0.18, 400); g.fillText(body, tx, y + h * 0.7);
  g.fillStyle = PAL.mute; g.font = font(h * 0.15, 500); g.textAlign = 'right'; g.fillText(time, x + w - h * 0.2, y + h * 0.38);
  if (bd) badge(g, x + h * 0.22 + s, y + (h - s) / 2, bd, h / 76);
  g.restore();
}
/** File icon (centre anchor, at s = 1: 44×56 + file name) */
export function fileIcon(g, x, y, s, o = {}) {
  const { name = 'Untitled.txt', ext = 'TXT', tint = '#8A90A0', cheap = true, label = true } = o;
  const w = 44 * s, h = 56 * s, x0 = x - w / 2, y0 = y - h / 2 - 8 * s, f = 12 * s;
  g.save();
  if (cheap) { g.fillStyle = 'rgba(0,0,0,.35)'; rr(g, x0 + 2 * s, y0 + 4 * s, w, h, 5 * s); g.fill(); }
  const gr = g.createLinearGradient(0, y0, 0, y0 + h); gr.addColorStop(0, '#E9ECF3'); gr.addColorStop(1, '#B9BFCC');
  g.fillStyle = gr; g.beginPath(); g.moveTo(x0 + 5 * s, y0); g.lineTo(x0 + w - f, y0); g.lineTo(x0 + w, y0 + f); g.lineTo(x0 + w, y0 + h - 5 * s);
  g.quadraticCurveTo(x0 + w, y0 + h, x0 + w - 5 * s, y0 + h); g.lineTo(x0 + 5 * s, y0 + h); g.quadraticCurveTo(x0, y0 + h, x0, y0 + h - 5 * s); g.lineTo(x0, y0 + 5 * s); g.quadraticCurveTo(x0, y0, x0 + 5 * s, y0); g.fill();
  g.fillStyle = '#9EA5B4'; g.beginPath(); g.moveTo(x0 + w - f, y0); g.lineTo(x0 + w - f, y0 + f); g.lineTo(x0 + w, y0 + f); g.fill();
  g.fillStyle = tint; rr(g, x0 + 5 * s, y0 + h - 19 * s, w - 10 * s, 12 * s, 3 * s); g.fill();
  g.fillStyle = '#fff'; g.font = font(8 * s, 700); g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(ext, x, y0 + h - 13 * s);
  g.fillStyle = 'rgba(40,46,60,.28)'; for (let i = 0; i < 3; i++) g.fillRect(x0 + 8 * s, y0 + (14 + i * 6) * s, (w - 18 * s) * (i === 2 ? 0.6 : 1), 2 * s);
  if (label) { g.font = font(9 * s, 500, 'mono'); g.fillStyle = PAL.text; g.textBaseline = 'top'; g.fillText(name.length > 16 ? name.slice(0, 15) + '…' : name, x, y0 + h + 5 * s); }
  g.restore();
}
/** Procedural landscape photo (top-left anchor) */
const SKY = [['#F7B267', '#F4845F', '#7D4E88'], ['#8EC5FC', '#A7C7E7', '#E0C3FC'], ['#2B3A67', '#496A81', '#F2A65A'], ['#9BE3DE', '#BEEBE9', '#F4DADA'], ['#FFD194', '#D1913C', '#5C3D2E'], ['#3A1C71', '#D76D77', '#FFAF7B']];
export function photo(g, x, y, w, h, seed = 1, o = {}) {
  const { border = true, cheap = true, r = Math.min(w, h) * 0.06 } = o;
  const R = mulberry(seed * 7919 + 13), sky = SKY[Math.floor(R() * SKY.length)];
  g.save();
  if (cheap) { g.fillStyle = 'rgba(0,0,0,.4)'; rr(g, x + 3, y + 6, w, h, r); g.fill(); }
  rr(g, x, y, w, h, r); g.clip();
  const gr = g.createLinearGradient(0, y, 0, y + h); gr.addColorStop(0, sky[0]); gr.addColorStop(0.6, sky[1]); gr.addColorStop(1, sky[2]);
  g.fillStyle = gr; g.fillRect(x, y, w, h);
  g.fillStyle = 'rgba(255,250,235,.85)'; g.beginPath(); g.arc(x + w * (0.2 + R() * 0.6), y + h * (0.25 + R() * 0.25), h * (0.07 + R() * 0.06), 0, TAU); g.fill();
  for (let L = 0; L < 3; L++) {
    const base = y + h * (0.55 + L * 0.15); g.fillStyle = `rgba(${20 + L * 8},${24 + L * 6},${40 - L * 6},${0.35 + L * 0.25})`;
    g.beginPath(); g.moveTo(x, y + h); let px = x; g.lineTo(x, base);
    while (px < x + w) { px += w * (0.08 + R() * 0.16); g.lineTo(Math.min(px, x + w), base - h * (R() * 0.22)); }
    g.lineTo(x + w, y + h); g.fill();
  }
  g.restore();
  if (border) { g.save(); g.strokeStyle = 'rgba(255,255,255,.18)'; g.lineWidth = 1; rr(g, x + 0.5, y + 0.5, w - 1, h - 1, r); g.stroke(); g.restore(); }
}
/** Window (top-left anchor): 40px title bar (small icon + title, no system buttons), returns the content-area rectangle */
export function windowBox(g, x, y, w, h, o = {}) {
  const { title = 'Untitled', app = 6, cheap = false, alpha = 1, r = 14, bar = 40 } = o;
  g.save(); g.globalAlpha *= alpha;
  panel(g, x, y, w, h, { r, fill: PAL.surf, cheap, shadow: 1 });
  g.fillStyle = 'rgba(255,255,255,.025)'; rr(g, x + 1, y + 1, w - 2, bar, r); g.fill();
  g.fillStyle = PAL.line; g.fillRect(x, y + bar, w, 1);
  appIcon(g, x + 14, y + bar / 2 - 9, 18, app);
  g.fillStyle = PAL.dim; g.font = font(14, 500); g.textBaseline = 'middle'; g.fillText(title, x + 42, y + bar / 2 + 0.5);
  g.restore();
  return [x, y + bar + 1, w, h - bar - 1];
}
/** Window content: kind = note | inbox | browser | sheet | chat | viewer | code */
export function windowContent(g, rect, kind, o = {}) {
  const [x, y, w, h] = rect, { seed = 1, n = 6, scroll = 0, text = '', tabs = 6, unread = 0 } = o;
  const R = mulberry(seed * 131 + 7);
  g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip();
  if (kind === 'inbox') {
    const rh = 46; const off = scroll % rh;
    for (let i = -1; i < h / rh + 1; i++) {
      const yy = y + i * rh - off + 8, k = i + Math.floor(scroll / rh);
      if (hash(k * 3.1 + seed) < 0.6 || k < unread) { g.fillStyle = '#5B8CFF'; g.beginPath(); g.arc(x + 16, yy + 16, 4, 0, TAU); g.fill(); }
      g.fillStyle = PAL.text; g.font = font(13, 600); g.textBaseline = 'alphabetic';
      g.fillText(['Weekly digest', 'Re: Re: Fwd: final deck', 'Your order shipped', 'Invoice #2291', 'Team sync moved', 'Don’t miss this', 'Security alert', 'Photos from Sat'][(k % 8 + 8) % 8], x + 30, yy + 20);
      g.fillStyle = PAL.mute; g.fillRect(x + 30, yy + 28, w * (0.4 + hash(k * 1.7) * 0.4), 5);
      g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(x + 12, yy + rh - 8, w - 24, 1);
    }
  } else if (kind === 'browser') {
    const tw = (w - 16) / tabs;
    for (let i = 0; i < tabs; i++) {
      g.fillStyle = i === tabs - 1 ? PAL.surf3 : 'rgba(255,255,255,.04)'; rr(g, x + 8 + i * tw, y + 6, Math.max(1, tw - 3), 26, Math.min(7, tw / 3)); g.fill();
      if (tw > 34) { appIcon(g, x + 14 + i * tw, y + 12, 14, i + seed); }
      if (tw > 90) { g.fillStyle = PAL.dim; g.font = font(11, 500); g.textBaseline = 'middle'; g.fillText('New Tab', x + 34 + i * tw, y + 19); }
    }
    g.fillStyle = 'rgba(255,255,255,.05)'; rr(g, x + 12, y + 40, w - 24, 24, 12); g.fill();
    for (let i = 0; i < 5; i++) { g.fillStyle = 'rgba(255,255,255,.06)'; g.fillRect(x + 20, y + 84 + i * 26, (w - 40) * (0.5 + R() * 0.5), 10); }
  } else if (kind === 'sheet') {
    const cw = 64, ch = 24; g.strokeStyle = 'rgba(255,255,255,.06)'; g.lineWidth = 1;
    for (let i = 0; i <= w / cw; i++) { g.beginPath(); g.moveTo(x + i * cw + 0.5, y); g.lineTo(x + i * cw + 0.5, y + h); g.stroke(); }
    for (let j = 0; j <= h / ch; j++) { g.beginPath(); g.moveTo(x, y + j * ch + 0.5); g.lineTo(x + w, y + j * ch + 0.5); g.stroke(); }
    g.fillStyle = PAL.dim; g.font = font(11, 500, 'mono'); g.textBaseline = 'middle';
    for (let j = 0; j < h / ch; j++) for (let i = 0; i < w / cw; i++) if (R() < 0.55) g.fillText(String(Math.floor(R() * 9000 + 100)), x + i * cw + 8, y + j * ch + 12);
  } else if (kind === 'chat') {
    for (let i = 0; i < n; i++) {
      const me = R() < 0.4, bw = w * (0.35 + R() * 0.3), yy = y + 14 + i * 40;
      g.fillStyle = me ? 'rgba(91,124,250,.35)' : 'rgba(255,255,255,.07)'; rr(g, me ? x + w - bw - 14 : x + 14, yy, bw, 30, 14); g.fill();
    }
  } else if (kind === 'viewer') {
    photo(g, x + 10, y + 10, w - 20, h - 20, seed, { cheap: false });
  } else if (kind === 'code') {
    for (let i = 0; i < h / 20; i++) { const ind = Math.floor(R() * 4) * 18; g.fillStyle = `rgba(255,255,255,${0.05 + R() * 0.08})`; g.fillRect(x + 20 + ind, y + 14 + i * 20, (w - 60 - ind) * (0.2 + R() * 0.7), 8); }
  } else if (kind === 'note') {
    g.fillStyle = 'rgba(255,255,255,.035)'; g.fillRect(x, y, w, h);
  }
  g.restore();
}
/** Storage bar */
export function storageBar(g, x, y, w, h, p, o = {}) {
  const { label = 'Storage almost full', value = '' } = o;
  g.save();
  g.fillStyle = 'rgba(255,255,255,.06)'; rr(g, x, y, w, h, h / 2); g.fill();
  const c = p > 0.85 ? PAL.red : mix('#8A90A0', PAL.red, clamp((p - 0.6) / 0.25));
  g.fillStyle = typeof c === 'string' ? c : PAL.red; g.shadowColor = rgba(PAL.red, p > 0.85 ? 0.6 : 0); g.shadowBlur = h;
  rr(g, x, y, w * p, h, h / 2); g.fill(); g.shadowColor = 'transparent';
  g.fillStyle = PAL.text; g.font = font(h * 1.1, 600); g.textBaseline = 'bottom'; g.fillText(label, x, y - h * 0.8);
  g.fillStyle = PAL.dim; g.font = font(h * 0.9, 500, 'mono'); g.textAlign = 'right'; g.fillText(value, x + w, y - h * 0.8);
  g.restore();
}

// ───────────────────────── Snap grid · flight · motion blur ─────────────────────────
/** Snap-grid slots: cols×rows, tile side length, gap spacing, origin (x0,y0) */
export function snapGrid(cols, rows, tile, gap, x0, y0) {
  const out = []; for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) out.push({ i, j, x: x0 + i * (tile + gap) + tile / 2, y: y0 + j * (tile + gap) + tile / 2 });
  return out;
}
/** Greedy nearest assignment: items[{x,y}] → slots, returns an array of slot indices (each element goes to the nearest free slot = "snap") */
export function assignSlots(items, slots) {
  const pairs = [];
  items.forEach((a, i) => slots.forEach((s, j) => pairs.push([(a.x - s.x) ** 2 + (a.y - s.y) ** 2, i, j])));
  pairs.sort((p, q) => p[0] - q[0]);
  const res = new Array(items.length).fill(-1), used = new Set(); let left = items.length;
  for (const [, i, j] of pairs) { if (res[i] >= 0 || used.has(j)) continue; res[i] = j; used.add(j); if (--left === 0) break; }
  return res;
}
/** Snap flight: from/to = {x,y,rot,s}, p 0..1 → position with elastic overshoot, rotation springs back to zero, morph shape transition */
export function flyPose(from, to, p, o = {}) {
  const { over = 1.35 } = o; const q = back(p, over), r = spring(p * 1.2, 9, 0.42);
  return { x: lerp(from.x, to.x, q), y: lerp(from.y, to.y, q), rot: lerp(from.rot || 0, to.rot || 0, clamp(r)), s: lerp(from.s ?? 1, to.s ?? 1, eo(p)), morph: ss(seg(p, 0.15, 0.7)) };
}
/** Motion blur: take n samples over [p-span, p] and draw each once (older ones fainter), draw(pSample, alpha) */
export function motionBlur(p, span, n, draw) {
  if (span <= 0 || n <= 1) { draw(p, 1); return; }
  for (let k = n - 1; k >= 0; k--) { const pk = p - span * k / (n - 1); const a = k === 0 ? 1 : 0.5 * (1 - k / n) / (n - 1) * 2.2; draw(pk, Math.min(1, a)); }
}

// ───────────────────────── Light-sweep reveal / strip perspective ─────────────────────────
/**
 * Light-sweep reveal: draws src into (dx,dy,dw,dh). p 0..1 light-band position: where the light has swept lights up and stays lit, a narrow highlight at the leading edge, unswept areas keep only the base brightness.
 * angle light-band direction (radians, default top-left → bottom-right), soft leading-edge softness (pixels)
 */
export function lightReveal(g, src, dx, dy, dw, dh, p, o = {}) {
  const { base = 0.07, angle = 0.62, soft = 260, band = 90, glint = 0.5, keep = 1 } = o;
  const [c, t] = buf('reveal', Math.ceil(dw), Math.ceil(dh));
  const ca = Math.cos(angle), sa = Math.sin(angle);
  const L = Math.abs(dw * ca) + Math.abs(dh * sa);   // total length along the light band's normal
  const front = -soft + p * (L + soft * 2);
  const cx = dw / 2, cy = dh / 2;
  const p0 = [cx - ca * L / 2, cy - sa * L / 2], at = d => [p0[0] + ca * d, p0[1] + sa * d];
  // Lit version: src × mask (lit before front)
  t.drawImage(src, 0, 0, dw, dh);
  t.globalCompositeOperation = 'destination-in';
  const A = at(front - soft), B = at(front);
  let gr = t.createLinearGradient(A[0], A[1], B[0], B[1]);
  gr.addColorStop(0, `rgba(0,0,0,${keep})`); gr.addColorStop(1, 'rgba(0,0,0,0)');
  t.fillStyle = gr; t.fillRect(0, 0, dw, dh);
  g.save(); g.globalAlpha = base; g.drawImage(src, dx, dy, dw, dh); g.globalAlpha = 1; g.drawImage(c, dx, dy); g.restore();
  // Leading-edge highlight: only where src has pixels
  if (glint > 0 && p > 0 && p < 1) {
    const [c2, t2] = buf('reveal2', Math.ceil(dw), Math.ceil(dh));
    t2.drawImage(src, 0, 0, dw, dh); t2.globalCompositeOperation = 'source-in';
    const A2 = at(front - band * 1.6), B2 = at(front + band * 0.4);
    const g2 = t2.createLinearGradient(A2[0], A2[1], B2[0], B2[1]);
    g2.addColorStop(0, 'rgba(255,255,255,0)'); g2.addColorStop(0.7, `rgba(235,240,255,${glint})`); g2.addColorStop(1, 'rgba(255,255,255,0)');
    t2.fillStyle = g2; t2.fillRect(0, 0, dw, dh);
    g.save(); g.globalCompositeOperation = 'lighter'; g.drawImage(c2, dx, dy); g.restore();
  }
}
/**
 * Strip perspective (rotating about the Y axis): treats src as a flat slab centred at (cx,cy), screen size w×h, rotY in radians (positive = right side turns away).
 * Returns map(u,v) → screen coordinates (u,v ∈ 0..1), handy for placing highlights / pushing in on the perspective plane
 */
export function perspective(g, src, cx, cy, w, h, rotY, o = {}) {
  const { slices = 96, dist = 2.2, alpha = 1 } = o;
  const D = dist * w, cs = Math.cos(rotY), sn = Math.sin(rotY);
  const map = (u, v) => { const X = (u - 0.5) * w, Z = X * sn, f = D / (D + Z); return [cx + X * cs * f, cy + (v - 0.5) * h * f]; };
  g.save(); g.globalAlpha *= alpha;
  const sw = src.width / slices;
  for (let i = 0; i < slices; i++) {
    const u0 = i / slices, u1 = (i + 1) / slices;
    const [x0] = map(u0, 0.5), [x1] = map(u1, 0.5);
    const X = ((u0 + u1) / 2 - 0.5) * w, f = D / (D + X * sn), hh = h * f;
    g.drawImage(src, i * sw, 0, sw, src.height, Math.min(x0, x1) - 0.35, cy - hh / 2, Math.abs(x1 - x0) + 0.7, hh);
  }
  g.restore();
  return map;
}

// ───────────────────────── Scrambled rolling digits ─────────────────────────
const GLYPH = '0123456789#%/*+=<>?$&@ABCDEFXZ';
/**
 * Scramble that rolls into the answer: each character of text has its own lock time locks[i] (seconds). Before locking it jumps randomly at 24fps (with vertical motion blur); on locking it drops into place (spring).
 * (x,y) is the left end of the baseline; o.align='center' centres it; o.colorOf(i) per-character colour
 */
export function scramble(g, text, x, y, t, locks, o = {}) {
  const { px = 200, wt = 600, fam = 'disp', color = PAL.text, colorOf = null, align = 'left', tracking = -0.04, start = -1e9, fps = 24 } = o;
  g.save(); g.font = font(px, wt, fam); g.textBaseline = 'alphabetic';
  const tw = [...text].map(c => g.measureText(c).width);
  const adv = tw.map(w => w + tracking * px), total = adv.reduce((a, b) => a + b, 0) - tracking * px;
  let cx = align === 'center' ? x - total / 2 : align === 'right' ? x - total : x;
  const f = Math.floor(t * fps);
  [...text].forEach((ch, i) => {
    const lk = locks[i] ?? locks[locks.length - 1], col = colorOf ? colorOf(i) : color;
    if (t < start) { cx += adv[i]; return; }
    const isDigit = /[0-9]/.test(ch);
    if (t < lk && isDigit) {
      const gch = GLYPH[Math.floor(hash(f * 13.7 + i * 91.3) * GLYPH.length)];
      g.fillStyle = col;
      for (let k = 0; k < 3; k++) { g.globalAlpha = [0.85, 0.3, 0.14][k]; g.fillText(gch, cx + (tw[i] - g.measureText(gch).width) / 2, y - k * px * 0.09); }
      g.globalAlpha = 1;
    } else if (t >= lk || !isDigit) {
      if (!isDigit && t < lk) { cx += adv[i]; return; }
      const d = t - lk, dy = d < 0.3 ? -px * 0.12 * Math.exp(-d * 14) * Math.cos(d * 40) : 0;
      g.fillStyle = col; g.globalAlpha = clamp(d * 30 + 0.4); g.fillText(ch, cx, y + dy); g.globalAlpha = 1;
    }
    cx += adv[i];
  });
  g.restore();
  return total;
}

// ───────────────────────── Caption bubble (toast) ─────────────────────────
/** UI caption bubble: bottom-centred pill + lime speaking dot. a 0..1 in/out, o.dense deepens it in the chaos section */
export function toast(g, text, a, o = {}) {
  if (a <= 0) return;
  const { y = H - 72, px = 40, dense = 0 } = o;
  g.save(); g.font = font(px, 500);
  const tw = g.measureText(text).width, h = px * 1.9, w = tw + px * 2.4, x = W / 2 - w / 2, yy = y - h + (1 - eo(a)) * 12;
  g.globalAlpha = eo(a);
  g.shadowColor = 'rgba(0,0,0,.5)'; g.shadowBlur = 40; g.shadowOffsetY = 10;
  g.fillStyle = `rgba(12,14,19,${0.72 + 0.16 * dense})`; rr(g, x, yy, w, h, h / 2); g.fill(); g.shadowColor = 'transparent';
  g.strokeStyle = 'rgba(255,255,255,.09)'; g.lineWidth = 1; rr(g, x + 0.5, yy + 0.5, w - 1, h - 1, h / 2); g.stroke();
  g.fillStyle = PAL.accent; g.shadowColor = rgba(PAL.accent, 0.8); g.shadowBlur = 10; g.beginPath(); g.arc(x + px * 0.95, yy + h / 2, px * 0.14, 0, TAU); g.fill(); g.shadowColor = 'transparent';
  g.fillStyle = PAL.text; g.textBaseline = 'middle'; g.fillText(text, x + px * 1.5, yy + h / 2 + 1);
  g.restore();
}

// ───────────────────────── 2.5D camera ─────────────────────────
/**
 * Camera: looks at world point (x,y), zoom = magnification of the desktop plane (z=0), rot Dutch angle, shake jitter in pixels.
 * A world point's height z (off the desktop toward the lens) → perspective scale s = 1/(1/zoom − z): the closer to the lens, the larger and the faster it moves (parallax).
 */
export function camera(c) {
  const { x = W / 2, y = H / 2, zoom = 1, rot = 0, sx = 0, sy = 0 } = c;
  const inv = 1 / zoom;
  const proj = (px, py, z = 0) => {
    const d = inv - z; if (d <= 0.02) return null;
    const s = 1 / d; let X = (px - x) * s, Y = (py - y) * s;
    const cr = Math.cos(rot), sr = Math.sin(rot);
    return { x: W / 2 + X * cr - Y * sr + sx, y: H / 2 + X * sr + Y * cr + sy, s };
  };
  /** Transform ctx to the plane at depth z (then draw in world coordinates) */
  const apply = (g, z = 0) => {
    const d = inv - z, s = 1 / Math.max(d, 0.02);
    g.setTransform(1, 0, 0, 1, 0, 0); g.translate(W / 2 + sx, H / 2 + sy); g.rotate(rot); g.scale(s, s); g.translate(-x, -y);
    return s;
  };
  return { x, y, zoom, rot, sx, sy, proj, apply };
}

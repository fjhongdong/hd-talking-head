// Procedural textures (Canvas2D): wallpaper, carpet, ceiling tiles, fluorescent light grilles, notices, exit sign
// All deterministic (mulberry seed), no external images
import * as THREE from 'three';
import { mulberry } from '/core/lib.js';

const cv = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
function tex(c, { srgb = true, repeat = true, aniso = 8 } = {}) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = aniso; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}
// Paper/cloth texture base noise: lots of small translucent dots
function grain(x, w, h, n, a, R, cols) {
  for (let i = 0; i < n; i++) {
    x.fillStyle = cols[Math.floor(R() * cols.length)]; x.globalAlpha = a * (0.3 + R() * 0.7);
    const s = 1 + R() * 2; x.fillRect(R() * w, R() * h, s, s);
  }
  x.globalAlpha = 1;
}

// Wallpaper: one texture = 0.53 m wide (one wallpaper roll) × 0.53 m high, repeating vertically
// Old-style office wallpaper: warm yellow ground + thin vertical stripes + a column of small diamonds/herringbone between pairs of stripes, faded, print slightly misregistered
export function wallpaper() {
  const S = 512, c = cv(S, S), x = c.getContext('2d'), R = mulberry(11);
  x.fillStyle = '#d5bd66'; x.fillRect(0, 0, S, S);
  // Slight vertical colour banding (uneven printing)
  for (let i = 0; i < S; i += 2) { x.fillStyle = `rgba(120,100,40,${0.03 + 0.03 * Math.sin(i * 0.05) ** 2})`; x.fillRect(i, 0, 2, S); }
  const cols = 8, cw = S / cols;
  for (let k = 0; k < cols; k++) {
    const x0 = k * cw;
    if (k % 2) { x.fillStyle = 'rgba(150,120,40,.10)'; x.fillRect(x0, 0, cw, S); }   // alternating wide and narrow ground stripes (the vertical stripes still read at a distance)
    // Double thin vertical lines
    x.fillStyle = 'rgba(140,112,40,.7)'; x.fillRect(x0 + 2, 0, 3, S); x.fillRect(x0 + 8, 0, 2, S);
    // Diamond column (one every 32px), alternating filled/hollow
    for (let j = 0; j < S / 32; j++) {
      const cx = x0 + cw * 0.6 + 0.8, cy = j * 32 + 16 + (k % 2) * 16;
      x.beginPath(); x.moveTo(cx, cy - 7); x.lineTo(cx + 5, cy); x.lineTo(cx, cy + 7); x.lineTo(cx - 5, cy); x.closePath();
      if ((j + k) % 2) { x.fillStyle = 'rgba(150,122,48,.55)'; x.fill(); }
      else { x.strokeStyle = 'rgba(150,122,48,.6)'; x.lineWidth = 1.8; x.stroke(); }
    }
  }
  grain(x, S, S, 26000, 0.08, R, ['#8a7433', '#f3e6ad', '#6b5a26']);
  // Seam between widths (left edge): one light line + one dark line
  x.fillStyle = 'rgba(255,245,200,.35)'; x.fillRect(0, 0, 2, S);
  x.fillStyle = 'rgba(90,70,20,.35)'; x.fillRect(2, 0, 1, S);
  return tex(c);
}

// Carpet: low-pile industrial carpet, mustard brown + mottled; R/G/B texture + a separate greyscale "pile relief" map as the source for roughness/normals
export function carpet() {
  const S = 512, c = cv(S, S), x = c.getContext('2d'), R = mulberry(23);
  x.fillStyle = '#8c763c'; x.fillRect(0, 0, S, S);
  grain(x, S, S, 90000, 0.22, R, ['#6d5b2e', '#a88f55', '#7d6a38', '#b59c60', '#5d4d26']);
  // Fine tufted rows (very faint)
  for (let j = 0; j < S; j += 3) { x.fillStyle = `rgba(60,48,20,${0.05 + R() * 0.05})`; x.fillRect(0, j, S, 1); }
  return tex(c);
}

// Mineral-fibre ceiling tiles: 0.6 × 1.2 m each, the texture covers 1.2 × 1.2 (two tiles); the T-bar grid is drawn on the edges
export function ceiling() {
  const S = 512, c = cv(S, S), x = c.getContext('2d'), R = mulberry(31);
  x.fillStyle = '#d9d3b8'; x.fillRect(0, 0, S, S);
  // Wormhole-like small pits in the mineral-fibre tile
  for (let i = 0; i < 5200; i++) {
    x.fillStyle = `rgba(110,100,70,${0.18 + R() * 0.3})`;
    const w = 1 + R() * 2.5, h = 1 + R() * 1.2; x.fillRect(R() * S, R() * S, w, h);
  }
  grain(x, S, S, 20000, 0.1, R, ['#a79f82', '#eee8d0']);
  // T-bar grid: ~2.4cm wide (=10px), between two tiles
  x.fillStyle = '#e6e1cf';
  x.fillRect(0, 0, S, 5); x.fillRect(0, S - 5, S, 5); x.fillRect(0, 0, 5, S); x.fillRect(S - 5, 0, 5, S); x.fillRect(S / 2 - 5, 0, 10, S);
  x.fillStyle = 'rgba(70,60,40,.6)';
  x.fillRect(0, 5, S, 1); x.fillRect(0, S - 6, S, 1); x.fillRect(5, 0, 1, S); x.fillRect(S - 6, 0, 1, S); x.fillRect(S / 2 - 6, 0, 1, S); x.fillRect(S / 2 + 5, 0, 1, S);
  return tex(c);
}

// Fluorescent light grille (prismatic diffuser): 0.6 × 1.2 m; alpha channel = emissive area
export function troffer() {
  const W = 128, H = 256, c = cv(W, H), x = c.getContext('2d'), R = mulberry(41);
  x.fillStyle = '#9a9786'; x.fillRect(0, 0, W, H);        // metal frame
  x.fillStyle = '#fbfaf0'; x.fillRect(7, 7, W - 14, H - 14);
  // Prism pattern: fine grid
  for (let i = 7; i < W - 7; i += 4) { x.fillStyle = 'rgba(180,180,160,.25)'; x.fillRect(i, 7, 1, H - 14); }
  for (let j = 7; j < H - 7; j += 4) { x.fillStyle = 'rgba(180,180,160,.25)'; x.fillRect(7, j, W - 14, 1); }
  // The two tubes behind the diffuser are brighter
  const g1 = x.createLinearGradient(7, 0, W - 7, 0);
  g1.addColorStop(0, 'rgba(255,255,255,0)'); g1.addColorStop(.3, 'rgba(255,255,255,.5)'); g1.addColorStop(.36, 'rgba(255,255,255,0)');
  g1.addColorStop(.64, 'rgba(255,255,255,0)'); g1.addColorStop(.7, 'rgba(255,255,255,.5)'); g1.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g1; x.fillRect(7, 7, W - 14, H - 14);
  // Shadows of dead insects inside the diffuser (an old-office-building detail)
  for (let i = 0; i < 3; i++) { x.fillStyle = 'rgba(60,55,40,.35)'; x.beginPath(); x.ellipse(15 + R() * (W - 30), 20 + R() * (H - 40), 2 + R() * 3, 1 + R() * 2, R() * 3, 0, 7); x.fill(); }
  return tex(c, { repeat: false });
}

// Text layout
function wrap(x, text, maxW) {
  const words = text.split(' '), lines = []; let cur = '';
  for (const w of words) { const t = cur ? cur + ' ' + w : w; if (x.measureText(t).width > maxW && cur) { lines.push(cur); cur = w; } else cur = t; }
  if (cur) lines.push(cur); return lines;
}
export const RULES = [
  'The humming of the lights is normal.',
  'You are the only employee on this floor.',
  'If the lights flicker three times, do not look at the ceiling.',
  'There are no exits on this floor. If you see an EXIT sign, do not follow it.',
  'If a coworker waves at you, wave back.',
];
// Notice: portrait 0.34 × 0.46 m, 1020×1380 px (3px/mm); kind = 'rules' | 'six'
export function notice(kind = 'rules', { age = 0.5, seed = 5 } = {}) {
  const W = 1020, H = 1380, c = cv(W, H), x = c.getContext('2d'), R = mulberry(seed);
  // Paper: yellowish photocopy paper + yellower at the edges
  x.fillStyle = age > .5 ? '#ece4c6' : '#f2eedd'; x.fillRect(0, 0, W, H);
  const eg = x.createRadialGradient(W / 2, H / 2, H * 0.3, W / 2, H / 2, H * 0.75);
  eg.addColorStop(0, 'rgba(0,0,0,0)'); eg.addColorStop(1, `rgba(150,120,50,${0.18 + age * 0.2})`);
  x.fillStyle = eg; x.fillRect(0, 0, W, H);
  grain(x, W, H, 30000, 0.06, R, ['#8c7c55', '#fff9e6']);
  const ink = '#1d1b17', M = 80;
  x.fillStyle = ink; x.textBaseline = 'alphabetic';
  // Header: large bold type + thin rule
  x.font = "700 30px 'IBM Plex Sans Condensed'"; x.fillText('FLOOR STAFF — PLEASE READ', M, 118);
  x.fillText('FORM NS-01 (REV. 9)', W - M - x.measureText('FORM NS-01 (REV. 9)').width, 118);
  x.fillRect(M, 136, W - 2 * M, 5);
  x.font = "700 86px 'IBM Plex Sans Condensed'";
  if (kind === 'rules') {
    x.fillText('NIGHT SHIFT', M, 250); x.fillText('ORIENTATION', M, 340);
    x.font = "400 34px 'IBM Plex Sans'"; x.fillStyle = '#3a362d';
    x.fillText('Read before beginning your rounds.', M, 400);
    x.fillStyle = ink; x.fillRect(M, 432, W - 2 * M, 2);
    let y = 510;
    RULES.forEach((r, i) => {
      x.font = "700 44px 'IBM Plex Sans'"; x.fillText(`${i + 1}.`, M, y);
      x.font = "600 44px 'IBM Plex Sans'";
      for (const ln of wrap(x, r, W - 2 * M - 70)) { x.fillText(ln, M + 70, y); y += 56; }
      y += 30;
    });
    x.fillRect(M, H - 170, W - 2 * M, 2);
    x.font = "400 30px 'IBM Plex Sans'"; x.fillStyle = '#3a362d';
    x.fillText('Thank you for your cooperation.', M, H - 118);
    x.fillText('Management', M, H - 78);
  } else {
    x.fillText('NIGHT SHIFT', M, 250); x.fillText('ORIENTATION', M, 340);
    x.font = "400 34px 'IBM Plex Sans'"; x.fillStyle = '#3a362d';
    x.fillText('(continued)', M, 400);
    x.fillStyle = ink; x.fillRect(M, 432, W - 2 * M, 2);
    x.font = "700 78px 'IBM Plex Sans'"; x.fillText('6.', M, 640);
    x.font = "700 78px 'IBM Plex Sans'";
    let y = 640; for (const ln of wrap(x, 'Do not rewind this tape.', W - 2 * M - 110)) { x.fillText(ln, M + 110, y); y += 96; }
    x.fillRect(M, H - 170, W - 2 * M, 2);
    x.font = "400 30px 'IBM Plex Sans'"; x.fillStyle = '#3a362d';
    x.fillText('Your orientation is complete.', M, H - 118);
  }
  // Photocopier grey specks, one fold crease
  for (let i = 0; i < 90; i++) { x.fillStyle = `rgba(30,30,30,${R() * 0.25})`; x.fillRect(R() * W, R() * H, 1 + R() * 3, 1 + R() * 2); }
  x.fillStyle = 'rgba(0,0,0,.05)'; x.fillRect(0, H * 0.52, W, 3); x.fillStyle = 'rgba(255,255,255,.25)'; x.fillRect(0, H * 0.52 + 3, W, 2);
  return tex(c, { repeat: false, aniso: 16 });
}

// Corkboard
export function cork() {
  const S = 256, c = cv(S, S), x = c.getContext('2d'), R = mulberry(51);
  x.fillStyle = '#a07a4a'; x.fillRect(0, 0, S, S);
  grain(x, S, S, 16000, 0.45, R, ['#6e4f2a', '#c49a62', '#8a6436', '#d8b07a']);
  return tex(c);
}

// Exit sign panel: red EXIT on white + arrows on both sides; alpha = emissive strength
export function exitSign() {
  const W = 512, H = 256, c = cv(W, H), x = c.getContext('2d');
  x.fillStyle = '#1a1512'; x.fillRect(0, 0, W, H);
  x.fillStyle = '#ff2a1a'; x.font = "700 150px 'IBM Plex Sans Condensed'"; x.textAlign = 'center'; x.textBaseline = 'middle';
  x.fillText('EXIT', W / 2, H / 2 + 8);
  x.beginPath(); x.moveTo(40, H / 2); x.lineTo(80, H / 2 - 34); x.lineTo(80, H / 2 + 34); x.closePath(); x.fill();
  x.beginPath(); x.moveTo(W - 40, H / 2); x.lineTo(W - 80, H / 2 - 34); x.lineTo(W - 80, H / 2 + 34); x.closePath(); x.fill();
  return tex(c, { repeat: false });
}

// Power socket plate
export function outlet() {
  const W = 64, H = 112, c = cv(W, H), x = c.getContext('2d');
  x.fillStyle = '#e8e2cc'; x.fillRect(0, 0, W, H);
  x.strokeStyle = 'rgba(0,0,0,.25)'; x.lineWidth = 2; x.strokeRect(1, 1, W - 2, H - 2);
  for (const cy of [32, 80]) {
    x.fillStyle = '#d7d0b8'; x.beginPath(); x.ellipse(W / 2, cy, 17, 20, 0, 0, 7); x.fill();
    x.fillStyle = '#2a2620'; x.fillRect(W / 2 - 9, cy - 9, 3, 10); x.fillRect(W / 2 + 6, cy - 9, 3, 10);
    x.beginPath(); x.arc(W / 2, cy + 9, 3, 0, 7); x.fill();
  }
  x.fillStyle = '#8b856f'; x.beginPath(); x.arc(W / 2, H / 2, 3, 0, 7); x.fill();
  return tex(c, { repeat: false });
}

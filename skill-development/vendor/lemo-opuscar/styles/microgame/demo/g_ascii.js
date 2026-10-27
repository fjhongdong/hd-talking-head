// ASCII terminal look (learned from ascii-crt: the characters are the picture, a density ramp sorted by each glyph's real ink coverage, negative space, amber phosphor + glow + scanlines, barrel screen) — a simplified version written from scratch
import { pass, canvas } from './glpass.js';
import { clamp, hash } from '/core/lib.js';
const TAU = Math.PI * 2;
export const CW = 16, CH = 32, COLS = 120, ROWS = 34;
export const [lumC, lx] = canvas();                 // greyscale "negative": draw the shapes here
export const [txtC, tx] = canvas();                 // character layer: white text on black, fed into the CRT
const [smC, sx] = canvas(COLS, ROWS);
// Glyph ramp sorted by real ink coverage
let RAMP = null;
function buildRamp() {
  const cand = " .,:;-=+*oxO#%@";
  const [c, x] = canvas(40, 60); const res = [];
  for (const ch of cand) {
    x.fillStyle = '#000'; x.fillRect(0, 0, 40, 60); x.fillStyle = '#fff'; x.font = '60px VT'; x.textBaseline = 'top'; x.fillText(ch, 0, 0);
    const d = x.getImageData(0, 0, 40, 60).data; let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i];
    res.push([s, ch]);
  }
  res.sort((a, b) => a[0] - b[0]);
  const mx = res[res.length - 1][0];
  // drop glyphs whose ink coverage is too close
  const out = []; let last = -1; for (const [s, ch] of res) { const v = s / mx; if (v - last > .03 || ch === ' ') { out.push([v, ch]); last = v; } }
  RAMP = out;
}
export function clearAscii() {
  for (const x of [lx, tx]) { x.setTransform(1, 0, 0, 1, 0, 0); x.globalCompositeOperation = 'source-over'; x.globalAlpha = 1; x.fillStyle = '#000'; x.fillRect(0, 0, 1920, 1080); }
}
// Convert the negative region [c0,r0,c1,r1) (in cells) to characters drawn on the txt layer
export function rasterize(region = [0, 0, COLS, ROWS], o = {}) {
  if (!RAMP) buildRamp();
  sx.imageSmoothingEnabled = true; sx.imageSmoothingQuality = 'high';
  sx.clearRect(0, 0, COLS, ROWS); sx.drawImage(lumC, 0, 0, 1920, 1080, 0, 0, COLS, ROWS);
  const d = sx.getImageData(0, 0, COLS, ROWS).data;
  tx.save(); tx.font = `${CH}px VT`; tx.textBaseline = 'top'; tx.fillStyle = '#fff';
  const [c0, r0, c1, r1] = region;
  for (let r = r0; r < r1; r++) for (let c = c0; c < c1; c++) {
    const at = (cc, rr) => d[(Math.max(0, Math.min(ROWS - 1, rr)) * COLS + Math.max(0, Math.min(COLS - 1, cc))) * 4] / 255;
    let L = at(c, r);
    if (L < .05) continue;
    L = clamp(L + (hash(c * 7.1 + r * 13.3 + (o.seed || 0)) - .5) * .05);
    let ch = ' '; for (const [v, g] of RAMP) { if (v <= L * .92) ch = g; else break; }
    // edges: where the gradient is large, outline with structural glyphs (- / | \ _)
    const gx = at(c + 1, r) - at(c - 1, r), gy = (at(c, r + 1) - at(c, r - 1)) * 2, gm = Math.hypot(gx, gy);
    if (o.edges !== false && gm > .55 && L < .85) {
      const a = (Math.atan2(gy, gx) * 180 / Math.PI + 180) % 180;   // gradient direction; the edge is perpendicular to it
      ch = a < 22.5 || a >= 157.5 ? '|' : a < 67.5 ? '/' : a < 112.5 ? (gy > 0 ? '_' : '-') : '\\';
      L = Math.max(L, .8);
    }
    tx.globalAlpha = .7 + .3 * L;
    tx.fillText(ch, c * CW, r * CH);
  }
  tx.restore();
}
// Type text directly (terminal text): col,row are cell coordinates; inv = inverse video
export function type(str, col, row, o = {}) {
  tx.save(); tx.font = `${(o.size || 1) * CH}px VT`; tx.textBaseline = 'top';
  const w = CW * (o.size || 1);
  if (o.inv) { tx.fillStyle = '#fff'; tx.fillRect(col * CW - 4, row * CH, str.length * w + 8, CH * (o.size || 1)); tx.fillStyle = '#000'; }
  else { tx.fillStyle = '#fff'; tx.globalAlpha = o.a ?? 1; }
  for (let i = 0; i < str.length; i++) tx.fillText(str[i], col * CW + i * w, row * CH);
  tx.restore();
}
export function print(g, o = {}) { g.drawImage(pass('crt', txtC, { on: o.on ?? 1, time: o.time || 0 }), 0, 0); }

// ───────── ASCII Dot: drawn on the greyscale negative (bright = dense characters) (x,y) = feet, s = scale ─────────
export function cadetAscii(x, y, s = 1, o = {}) {
  const g = lx; g.save(); g.translate(x, y); g.scale(s, s);
  const G = v => `rgb(${v * 255},${v * 255},${v * 255})`;
  const circ = (cx, cy, r, v) => { g.beginPath(); g.arc(cx, cy, r, 0, TAU); g.fillStyle = G(v); g.fill(); };
  const rr = (x0, y0, w, h, r, v) => { g.beginPath(); g.roundRect(x0, y0, w, h, r); g.fillStyle = G(v); g.fill(); };
  // antenna
  g.strokeStyle = G(.7); g.lineWidth = 5; g.beginPath(); g.moveTo(0, -240); g.lineTo(0, -282); g.stroke(); circ(0, -292, 14, 1);
  // backpack + body
  rr(-64, -140, 128, 96, 16, .45);
  rr(-54, -124, 108, 84, 22, .92);
  rr(-58, -66, 116, 14, 4, .35);
  rr(-20, -112, 40, 30, 6, .15);            // chest badge (dark = sparse characters, showing the 05 as a "hole")
  // legs + boots
  for (const sx2 of [-1, 1]) { rr(sx2 * 24 - 17, -56, 34, 40, 10, .8); rr(sx2 * 24 - 22, -22, 44, 24, 11, .55); }
  // arms
  if (o.pose === 'strap') { rr(-86, -118, 30, 60, 14, .85); rr(56, -118, 30, 60, 14, .85); circ(-70, -54, 15, .6); circ(70, -54, 15, .6); }
  else { rr(-86, -120, 28, 66, 14, .85); rr(58, -120, 28, 66, 14, .85); circ(-72, -52, 15, .6); circ(72, -52, 15, .6); }
  // neck ring
  g.beginPath(); g.ellipse(0, -124, 50, 15, 0, 0, TAU); g.fillStyle = G(.6); g.fill();
  // helmet: bright ring + dark glass + face
  circ(0, -178, 68, 1); circ(0, -178, 56, .0);
  circ(0, -172, 40, .42);
  g.beginPath(); g.ellipse(0, -212, 36, 12, 0, 0, TAU); g.fillStyle = G(.3); g.fill();   // hair
  for (const sx2 of [-1, 1]) circ(sx2 * 17, -176, 9, 0);                                   // eyes = empty
  if (o.face === 'happy') { g.fillStyle = G(0); g.fillRect(-10, -152, 20, 6); }
  else { g.fillStyle = G(0); g.fillRect(-8, -150, 16, 4); }
  // glass highlight
  g.strokeStyle = G(1); g.lineWidth = 6; g.beginPath(); g.arc(0, -178, 46, Math.PI * 1.1, Math.PI * 1.4); g.stroke();
  g.restore();
}
export function testCadet(g, t) {
  clearAscii();
  cadetAscii(700, 950, 2.6);
  rasterize();
  type('> CADET_05.PRF', 70, 6); type('  HELMET ... OK', 70, 8); type('  ANTENNA . OK', 70, 9); type(' SECURED ', 70, 12, { inv: true });
  print(g);
}
export function render(o = {}) { return pass('crt', txtC, { on: o.on ?? 1, time: o.time || 0, uflat: o.flat ? 1 : 0 }); }

// ───────── Hand-written ASCII Dot (template): round helmet outline + two eyes + antenna ball (the brightest @)─────────
export const DOT_ART = [
  "        (@)        ",
  "         |         ",
  "     .-'''''-.     ",
  "   .'         '.   ",
  "  /   (o) (o)   \\  ",
  " |               | ",
  " |     \\___/     | ",
  "  \\             /  ",
  "   '-._______.-'   ",
  "  __/|  05   |\\__  ",
  " (___|       |___) ",
  "     |  | |  |     ",
  "    (___) (___)    ",
];
// brightness: helmet outline / antenna ball brightest, face medium, body medium
function charLevel(r, c, ch) {
  if (r === 0 && ch === '@') return 1.25;
  if (r >= 2 && r <= 8 && "/\\|.'-_".includes(ch)) return 1;
  if (ch === 'o' || ch === '^' || ch === '_') return .95;
  return .8;
}
export function drawArt(art, col, row, size = 2, o = {}) {
  tx.save(); tx.font = `${CH * size}px VT`; tx.textBaseline = 'top';
  for (let r = 0; r < art.length; r++) for (let c = 0; c < art[r].length; c++) {
    const ch = art[r][c]; if (ch === ' ') continue;
    const L = (o.level || charLevel)(r, c, ch);
    const x = (col + c * size) * CW, y = (row + r * size) * CH;
    if (L > 1.1) { tx.fillStyle = '#fff'; tx.globalAlpha = 1; tx.fillRect(x - 4, y + 6, CW * size + 8, CH * size - 10); tx.globalAlpha = 1; tx.fillStyle = '#000'; tx.fillText(ch, x, y); continue; }
    tx.globalAlpha = Math.min(1, L); tx.fillStyle = '#fff'; tx.fillText(ch, x, y);
    tx.fillText(ch, x + 1.5, y); if (L >= 1) tx.fillText(ch, x + 3, y);   // bold
  }
  tx.restore();
}
// ───────── G3 STRAP IN! (local lt 0..4, 120 BPM; 8fps)─────────
export function sceneStrap(g, lt, o = {}) {
  const T = o.step === false ? lt : Math.floor(lt * 8) / 8;
  clearAscii();
  // top bar
  type(' FIVE-SECOND CAMP // TRAINING TERMINAL v0.5 '.padEnd(118, ' '), 1, 1, { inv: true });
  // log (typed out character by character on the right)
  const log = [[.8, '> STRAP_IN.EXE'], [1.0, '  SEAT ......... OK'], [1.5, '  BELT ........ ' + (T >= 2.5 ? 'LOCKED' : '....')], [2.5, '  BUCKLE ...... CLICK'], [3.0, '  CADET 05 .... SECURED']];
  log.forEach(([t0, s], i) => { if (T >= t0) { const n = Math.min(s.length, Math.floor((T - t0) * 60)); type(s.slice(0, n), 76, 6 + i * 2); } });
  if (T >= .8 && T < 3.0 && Math.floor(lt * 4) % 2) type('_', 76 + (T >= 2.5 ? 20 : 16), 6 + Math.min(4, Math.floor((T - .8) / .5)) * 2);
  // seat (large characters)
  const C0 = 5, R0 = 2.6, SZ = 2.2;
  const seat = ["|=============|", "|             |", "|             |", "|             |", "|             |", "|             |"];
  // Dot
  const happy = T >= 3.0;
  const art = DOT_ART.map(r => r);
  if (happy) art[4] = "  /   (^) (^)   \\  ";
  // seat belt: row 10, advances left to right in three steps, finally clicks into the buckle
  let belt = 0; for (const [t0, v] of [[1.0, 4], [1.5, 8], [2.0, 11], [2.5, 13]]) if (T >= t0) belt = v;
  const locked = T >= 2.5;
  const row10 = " (___|" + ('='.repeat(Math.min(belt, 7))).padEnd(7, ' ') + "|___) ";
  art[10] = row10;
  drawArt(art, C0, R0, SZ);
  // belt tail coming in from the left edge of the frame + buckle
  const by = R0 + 10 * SZ;
  if (belt > 0 && !locked) { type('='.repeat(Math.max(0, 12 - belt)).padStart(Math.round(C0 / SZ + 1), ' ').slice(-Math.round(C0 / SZ + 1)), 0, by, { size: SZ, a: .9 }); }
  type(locked ? '[##]' : '[  ]', C0 + 13 * SZ, by, { size: SZ, inv: locked && Math.floor(lt * 8) % 2 === 0 });
  // SECURED inverse-video flash
  if (T >= 3.0) type(' SECURED ', 80, 22, { size: 2, inv: Math.floor(lt * 6) % 2 === 0 });
  // bottom status bar
  type(`STRAP TENSION [${'#'.repeat(Math.round(Math.min(1, belt / 13) * 20)).padEnd(20, '.')}]`, 76, 18);
  print(g, { time: lt });
}

// Character-grid engine: VT323 glyph atlas + glyphs stamped cell by cell.
// Convention: the scene canvas is drawn with 'lighter' (additive); R channel = amber phosphor intensity, G channel = earth-blue intensity (crt.js does the colouring).
// Cell: width cw, height ch = 2cw (VT323 advance = 0.4em, glyphs 0.8em tall), font size fs = cw / 0.4.
export const W = 1920, H = 1080;
export const FONT = 'VT323';
const GS = 160;                 // atlas font size
const GW = GS * .4, GH = GS * .8, BASE = GS * .64;   // atlas cell 64×128, baseline 102.4
const PAD = 4;                  // padding between atlas cells so scaled sampling doesn't bleed between glyphs
const CHARS = [];
for (let c = 32; c < 127; c++) CHARS.push(String.fromCharCode(c));
CHARS.push('\u00d7');   // the × on the end card
export const COLS_ATLAS = 16;

export let ATLAS = null;        // { red, green, alpha:Uint8 per glyph, cov:{ch:coverage} }

export async function initTerm() {
  await document.fonts.load(`${GS}px ${FONT}`);
  const rows = Math.ceil(CHARS.length / COLS_ATLAS);
  const aw = COLS_ATLAS * (GW + PAD * 2), ah = rows * (GH + PAD * 2);
  const white = document.createElement('canvas'); white.width = aw; white.height = ah;
  const g = white.getContext('2d', { willReadFrequently: true });
  g.fillStyle = '#fff'; g.strokeStyle = '#fff'; g.font = `${GS}px ${FONT}`; g.textBaseline = 'alphabetic';
  g.lineJoin = 'round'; g.lineWidth = 2.2;      // a little electron-beam spread: glyphs get slightly fatter, edges rounder
  const pos = {};
  CHARS.forEach((ch, i) => {
    const x = (i % COLS_ATLAS) * (GW + PAD * 2) + PAD, y = Math.floor(i / COLS_ATLAS) * (GH + PAD * 2) + PAD;
    pos[ch] = [x, y];
    g.save(); g.beginPath(); g.rect(x, y, GW, GH); g.clip();
    g.fillText(ch, x, y + BASE); g.strokeText(ch, x, y + BASE);
    g.restore();
  });
  // coverage + an alpha bitmap per glyph (sampled inside the glyph during the fractal zoom)
  const cov = {}, bits = {};
  const d = g.getImageData(0, 0, aw, ah).data;
  for (const ch of CHARS) {
    const [x, y] = pos[ch]; let s = 0; const b = new Uint8Array(GW * GH);
    for (let j = 0; j < GH; j++) for (let i = 0; i < GW; i++) { const a = d[((y + j) * aw + x + i) * 4 + 3]; b[j * GW + i] = a; s += a; }
    cov[ch] = s / 255 / (GW * GH); bits[ch] = b;
  }
  // thin unstroked glyph bitmap: sampled during the fractal zoom so the gaps between strokes stay clearer
  const thin = {};
  { const c2 = document.createElement('canvas'); c2.width = GW; c2.height = GH; const x2 = c2.getContext('2d', { willReadFrequently: true });
    x2.font = `${GS}px ${FONT}`; x2.fillStyle = '#fff';
    for (const ch of CHARS) { x2.clearRect(0, 0, GW, GH); x2.fillText(ch, 0, BASE); const dd = x2.getImageData(0, 0, GW, GH).data; const b = new Uint8Array(GW * GH); for (let k = 0; k < GW * GH; k++) b[k] = dd[k * 4 + 3]; thin[ch] = b; } }
  const tint = col => { const c = document.createElement('canvas'); c.width = aw; c.height = ah; const x = c.getContext('2d');
    x.drawImage(white, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = col; x.fillRect(0, 0, aw, ah); return c; };
  ATLAS = { red: tint('#ff0000'), green: tint('#00ff00'), black: tint('#000000'), white, pos, cov, bits, thin, GW, GH };
  return ATLAS;
}

// Stamp one glyph: top-left corner (x,y), cell width cw; a = brightness 0..1+; chan 0 = amber, 1 = earth blue
export function glyph(g, ch, x, y, cw, a = 1, chan = 0) {
  if (ch === ' ' || a <= 0.004) return;
  const p = ATLAS.pos[ch]; if (!p) return;
  g.globalAlpha = Math.min(1, a);
  g.drawImage(chan ? ATLAS.green : ATLAS.red, p[0], p[1], GW, GH, x, y, cw, cw * 2);
  if (a > 1) { g.globalAlpha = Math.min(1, a - 1); g.drawImage(chan ? ATLAS.green : ATLAS.red, p[0], p[1], GW, GH, x, y, cw, cw * 2); }
}
// One line of text (starting at column col, row row), view = {ox, oy, cw}
export function text(g, str, col, row, view, a = 1, chan = 0) {
  const { ox, oy, cw } = view;
  for (let i = 0; i < str.length; i++) glyph(g, str[i], ox + (col + i) * cw, oy + row * cw * 2, cw, a, chan);
}
// Inverse video: solid block + glyph knocked out
export function inverse(g, str, col, row, view, a = 1, chan = 0) {
  const { ox, oy, cw } = view;
  const x = ox + col * cw, y = oy + row * cw * 2;
  g.globalAlpha = Math.min(1, a); g.fillStyle = chan ? '#00ff00' : '#ff0000';
  g.fillRect(x, y + cw * .1, str.length * cw, cw * 1.8);
  g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1;   // the scene canvas is opaque black, so knocking out = drawing the glyph in black
  for (let i = 0; i < str.length; i++) { const p = ATLAS.pos[str[i]]; if (p && str[i] !== ' ') g.drawImage(ATLAS.black, p[0], p[1], GW, GH, x + i * cw, y, cw, cw * 2); }
  g.globalCompositeOperation = 'lighter';
}
// Block cursor
export function cursor(g, col, row, view, a = 1, chan = 0) {
  const { ox, oy, cw } = view;
  g.globalAlpha = Math.min(1, a); g.fillStyle = chan ? '#00ff00' : '#ff0000';
  g.fillRect(ox + col * cw + cw * .06, oy + row * cw * 2 + cw * .22, cw * .88, cw * 1.56);
}

// Density table: sort a set of characters by measured ink coverage, multiply by the brightness attribute (dim/normal/bold) → table of levels
export function makeRamp(chars, attrs = [.42, .7, 1]) {
  const set = [...new Set(chars.split(''))].filter(c => c !== ' ');
  const mx = Math.max(...set.map(c => ATLAS.cov[c]));
  const lv = [{ ch: ' ', a: 0, v: 0 }];
  for (const c of set) for (const a of attrs) lv.push({ ch: c, a, v: ATLAS.cov[c] / mx * a });
  lv.sort((p, q) => p.v - q.v);
  // drop levels with near-duplicate brightness (keep the "bolder" character)
  const out = [lv[0]];
  for (const l of lv.slice(1)) { if (l.v - out[out.length - 1].v > .018) out.push(l); else if (l.a > out[out.length - 1].a) out[out.length - 1] = l; }
  return out;
}
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v + .5) / 16 - .5);
// Brightness L (0..1) → level (with 4×4 ordered dithering)
export function pick(ramp, L, i, j, dither = .6) {
  const n = ramp.length - 1;
  let hsh = Math.sin(i * 12.9898 + j * 78.233) * 43758.5453; hsh -= Math.floor(hsh);
  const x = L * n + (BAYER[(j & 3) * 4 + (i & 3)] * .5 + (hsh - .5) * .5) * dither * 1.6;
  const k = Math.max(0, Math.min(n, Math.round(x)));
  return ramp[k];
}

// Image → cells: art is a cols*sx × rows*sy canvas (R = amber brightness, G = earth brightness), averaged per cell
export function cellsFromImage(data, aw, cols, rows, sx, sy) {
  const A = new Float32Array(cols * rows), E = new Float32Array(cols * rows), N = new Float32Array(cols * rows);
  const n = sx * sy * 255;
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    let r = 0, gg = 0, bb = 0;
    for (let v = 0; v < sy; v++) { let o = ((j * sy + v) * aw + i * sx) * 4; for (let u = 0; u < sx; u++, o += 4) { r += data[o]; gg += data[o + 1]; bb += data[o + 2]; } }
    A[j * cols + i] = r / n; E[j * cols + i] = gg / n; N[j * cols + i] = bb / n;
  }
  return { A, E, N, cols, rows };
}

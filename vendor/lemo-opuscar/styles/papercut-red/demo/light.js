// Night lighting: image = paper (base colour lit from the front) × light map L + emission E (backlit window flowers) + glow + volumetric light
import { PAL, canvas, transmitOf } from './paper.js';
import { put } from './rig.js';
const W = 1920, H = 1080;
const [Lc, L] = canvas(W, H), [Ec, E] = canvas(W, H), [Hc, Hg] = canvas(W / 2, H / 2), [H2c, H2] = canvas(W / 2, H / 2);
export { L, E, Lc, Ec };
export function beginLight(amb = 'rgb(118,120,168)') {
  L.setTransform(1, 0, 0, 1, 0, 0); L.globalCompositeOperation = 'source-over'; L.globalAlpha = 1; L.fillStyle = amb; L.fillRect(0, 0, W, H);
  E.setTransform(1, 0, 0, 1, 0, 0); E.globalCompositeOperation = 'source-over'; E.clearRect(0, 0, W, H);
}
// radial warm light (added to the light map)
export function pool(x, y, r, col = 'rgba(255,196,120,1)', a = 1) {
  L.save(); L.setTransform(1, 0, 0, 1, 0, 0); L.globalCompositeOperation = 'lighter'; L.globalAlpha = a;
  const gr = L.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, col); gr.addColorStop(1, 'rgba(0,0,0,0)');
  L.fillStyle = gr; L.fillRect(x - r, y - r, r * 2, r * 2); L.restore();
}
// draw an image (projected pattern) onto the light map, M = transform, filter can blur it
export function lightImage(img, M, a = 1, col = null, blur = 0) {
  L.save(); L.setTransform(...M); L.globalCompositeOperation = 'lighter'; L.globalAlpha = a; if (blur) L.filter = `blur(${blur}px)`;
  if (col) { const [c, g] = canvas(img.c.width, img.c.height); g.drawImage(img.c, 0, 0); g.globalCompositeOperation = 'source-in'; g.fillStyle = col; g.fillRect(0, 0, c.width, c.height); L.drawImage(c, img.x0, img.y0, img.w, img.h); }
  else L.drawImage(img.c, img.x0, img.y0, img.w, img.h);
  L.restore();
}
// "fully lit" area on the light map (emissive areas such as windows keep their original brightness)
export function lightRect(fn) { L.save(); L.globalCompositeOperation = 'source-over'; L.fillStyle = '#fff'; L.beginPath(); fn(L); L.fill(); L.restore(); }
// projected pattern that falls only on one layer (the alpha of the mask canvas)
const [Mc, Mg] = canvas(W, H);
export function lightMasked(img, M, maskCanvas, a = 1, col = 'rgb(255,200,140)', blur = 0) {
  Mg.setTransform(1, 0, 0, 1, 0, 0); Mg.globalCompositeOperation = 'source-over'; Mg.clearRect(0, 0, W, H);
  Mg.setTransform(...M); if (blur) Mg.filter = `blur(${blur}px)`; Mg.drawImage(img.c, img.x0, img.y0, img.w, img.h); Mg.filter = 'none';
  Mg.setTransform(1, 0, 0, 1, 0, 0); Mg.globalCompositeOperation = 'source-in'; Mg.fillStyle = col; Mg.fillRect(0, 0, W, H);
  Mg.globalCompositeOperation = 'destination-in'; Mg.drawImage(maskCanvas, 0, 0);
  L.save(); L.setTransform(1, 0, 0, 1, 0, 0); L.globalCompositeOperation = 'lighter'; L.globalAlpha = a; L.drawImage(Mc, 0, 0); L.restore();
}
export function applyLight(g) { g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'multiply'; g.drawImage(Lc, 0, 0); g.restore(); }

// backlit window: draw a glowing window on ctx (light field × window-flower transmission). shape: {x,y,w,h} or {x,y,r} (world coordinates, C = world→screen)
// flower = tuanhua piece (optional), lattice = whether to draw the window lattice, I = brightness 0..1
export function glowWindow(ctx, C, win, I = 1, flower = null, opt = {}) {
  if (I <= 0.001) return;
  ctx.save(); ctx.setTransform(...C);
  ctx.beginPath(); if (win.r) ctx.arc(win.x, win.y, win.r + 1, 0, 7); else ctx.rect(win.x - win.w / 2 - 1, win.y - win.h / 2 - 1, win.w + 2, win.h + 2); ctx.clip();
  const R = win.r || Math.max(win.w, win.h) * .7, cx = win.x, cy = win.y + (win.r ? 0 : win.h * .1);
  const gr = ctx.createRadialGradient(cx, cy + R * .15, 0, cx, cy, R * 1.25);
  const k = I;
  gr.addColorStop(0, `rgba(255,${246},${214},${k})`); gr.addColorStop(.55, `rgba(255,${196},${110},${k})`); gr.addColorStop(1, `rgba(236,${120},${46},${k})`);
  ctx.fillStyle = '#140c10'; ctx.fillRect(win.x - R * 2, win.y - R * 2, R * 4, R * 4);
  ctx.fillStyle = gr; ctx.fillRect(win.x - R * 2, win.y - R * 2, R * 4, R * 4);
  // window-paper fibres
  ctx.globalCompositeOperation = 'multiply'; ctx.globalAlpha = .5 * k;
  if (opt.paperPat) { ctx.fillStyle = opt.paperPat; ctx.fillRect(win.x - R * 2, win.y - R * 2, R * 4, R * 4); }
  ctx.globalAlpha = 1;
  if (flower) put(ctx, flower.p, [...mulC(C, flower.M)], { img: transmitOf(flower.p, opt.tcol || '#c9241a'), shadow: 0 });
  if (opt.lattice) {
    ctx.strokeStyle = opt.tcol || '#b3201a'; ctx.lineWidth = opt.lw || 5;
    const { x, y, w, h } = win, n = opt.lattice;
    ctx.beginPath();
    for (let i = 1; i < n; i++) { ctx.moveTo(x - w / 2 + w * i / n, y - h / 2); ctx.lineTo(x - w / 2 + w * i / n, y + h / 2); ctx.moveTo(x - w / 2, y - h / 2 + h * i / n); ctx.lineTo(x + w / 2, y - h / 2 + h * i / n); }
    ctx.stroke();
    // small central tuanhua (the window flower for a square lattice window)
    if (opt.mini) { put(ctx, opt.mini, mulC(C, [w / 900, 0, 0, w / 900, x, y]), { img: transmitOf(opt.mini, opt.tcol || '#c9241a'), shadow: 0 }); }
  }
  ctx.restore();
}
const mulC = (A, B) => [A[0] * B[0] + A[2] * B[1], A[1] * B[0] + A[3] * B[1], A[0] * B[2] + A[2] * B[3], A[1] * B[2] + A[3] * B[3], A[0] * B[4] + A[2] * B[5] + A[4], A[1] * B[4] + A[3] * B[5] + A[5]];
// glow: two blurred layers of E added together
export function bloom(g, a = .8) {
  Hg.setTransform(1, 0, 0, 1, 0, 0); Hg.globalCompositeOperation = 'source-over'; Hg.clearRect(0, 0, W / 2, H / 2);
  Hg.filter = 'blur(10px)'; Hg.drawImage(Ec, 0, 0, W / 2, H / 2); Hg.filter = 'none';
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'lighter'; g.globalAlpha = a * .55; g.drawImage(Hc, 0, 0, W, H);
  H2.setTransform(1, 0, 0, 1, 0, 0); H2.clearRect(0, 0, W / 2, H / 2); H2.filter = 'blur(40px)'; H2.drawImage(Ec, 0, 0, W / 2, H / 2); H2.filter = 'none';
  g.globalAlpha = a * .7; g.drawImage(H2c, 0, 0, W, H); g.restore();
}
// volumetric light: scale E up around (cx,cy) and add many layers (zoom blur)
export function rays(g, cx, cy, a = .5, n = 18, maxS = 2.2, tint = null) {
  H2.setTransform(1, 0, 0, 1, 0, 0); H2.globalCompositeOperation = 'source-over'; H2.clearRect(0, 0, W / 2, H / 2);
  H2.globalCompositeOperation = 'lighter';
  for (let i = 0; i < n; i++) {
    const s = 1 + (maxS - 1) * i / (n - 1); H2.globalAlpha = (1 - i / n) * 1.6 / n;
    H2.setTransform(s / 2, 0, 0, s / 2, cx / 2 * (1 - s), cy / 2 * (1 - s)); H2.drawImage(Ec, 0, 0);
  }
  H2.setTransform(1, 0, 0, 1, 0, 0);
  if (tint) { H2.globalCompositeOperation = 'multiply'; H2.globalAlpha = 1; H2.fillStyle = tint; H2.fillRect(0, 0, W / 2, H / 2); }
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'lighter'; g.globalAlpha = a; g.filter = 'blur(3px)'; g.drawImage(H2c, 0, 0, W, H); g.restore();
}
// brighten (added onto the image, bypassing the light map): pattern × layer mask, composited with lighter → lit areas become brighter than the paper colour itself
const [Ac, Ag] = canvas(W, H);
export function addMasked(g, img, M, maskCanvas, col = 'rgb(255,190,130)', a = 1, blur = 0) {
  Ag.setTransform(1, 0, 0, 1, 0, 0); Ag.globalCompositeOperation = 'source-over'; Ag.clearRect(0, 0, W, H);
  Ag.setTransform(...M); if (blur) Ag.filter = `blur(${blur}px)`; Ag.drawImage(img.c, img.x0, img.y0, img.w, img.h); Ag.filter = 'none';
  Ag.setTransform(1, 0, 0, 1, 0, 0); Ag.globalCompositeOperation = 'source-in'; Ag.fillStyle = col; Ag.fillRect(0, 0, W, H);
  if (maskCanvas) { Ag.globalCompositeOperation = 'destination-in'; Ag.drawImage(maskCanvas, 0, 0); }
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'lighter'; g.globalAlpha = a; g.drawImage(Ac, 0, 0); g.restore();
}

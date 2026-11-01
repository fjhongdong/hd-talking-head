// Park, top-down embankment, printer output tray, bike-bell close-up
import { g, W, H, rect, rrect, poly, blob, line, curve, circle, ellipse, over, inkA, ring, text, S } from './draw.js';
import { mulberry, hash } from '/core/lib.js';
import { bands, lamp } from './scenes.js';
import { PAL, baguette } from './rider.js';

// ───────── Park ─────────
export const PARK = { hz: 600, path: 900 };
function blossom(x, yb, sc, seed, t) {
  const R = mulberry(seed);
  line([[x, yb], [x - 6 * sc, yb - 150 * sc]], 18 * sc, [1, 0, .35]);
  line([[x - 4 * sc, yb - 120 * sc], [x + 40 * sc, yb - 190 * sc]], 10 * sc, [1, 0, .35]);
  line([[x - 6 * sc, yb - 140 * sc], [x - 50 * sc, yb - 200 * sc]], 10 * sc, [1, 0, .35]);
  const pts = []; for (let i = 0; i < 14; i++) { const a = i / 14 * Math.PI * 2, r = (120 + R() * 40) * sc; pts.push([x + Math.cos(a) * r * 1.15, yb - 250 * sc + Math.sin(a) * r * .8]); }
  blob(pts, [0, .08, 1]);
  for (let k = 0; k < 7; k++) { const a = R() * 6.28, r = R() * 90 * sc; circle(x + Math.cos(a) * r, yb - 250 * sc + Math.sin(a) * r * .7, (22 + R() * 20) * sc, [.35, 0, 1]); }
  for (let k = 0; k < 9; k++) { const a = R() * 6.28, r = R() * 110 * sc; circle(x + Math.cos(a) * r, yb - 260 * sc + Math.sin(a) * r * .7, (8 + R() * 8) * sc, [0, .0, .35]); }
}
export function park(o = {}) {
  const cx = o.cx || 0, t = o.t || 0, HZ = PARK.hz;
  bands(0, HZ, [[0, .7, .05], [0, .45, .04], [0, .26, .02], [0, .12, 0]]);
  // distant city (parallax .15)
  g.beginPath();
  for (let k = -2; k < 26; k++) { const X = k * 120 - (cx * .15) % 120, hh = 50 + hash(k + Math.floor(cx * .15 / 120)) * 80; g.rect(X, HZ - hh, 122, hh + 4); }
  g.fillStyle = inkA([.4, 0, .1]); g.fill();
  // lawn (yellow solid + blue halftone = green)
  rect(0, HZ, W, H - HZ, [.42, .9, 0]);
  rect(0, HZ, W, 40, [.55, .9, .05]);
  // back row of cherry trees (parallax .5)
  for (let k = -1; k < 12; k++) { const X = k * 260 + 60 - ((cx * .5) % 260); blossom(X, HZ + 40, .55, 100 + ((k + Math.floor(cx * .5 / 260)) % 7 + 7) % 7, t); }
  // path
  rect(0, PARK.path - 34, W, 74, [0, .16, .08]);
  rect(0, PARK.path - 36, W, 5, [.6, .3, .1]); rect(0, PARK.path + 40, W, 5, [.6, .3, .1]);
  // bench + street lamp (parallax 1)
  for (let k = -1; k < 8; k++) {
    const X = k * 700 + 420 - cx; if (X < -300 || X > W + 300) continue;
    if (k % 2) lamp(X, PARK.path - 40, 280, 0);
    else { rect(X - 70, PARK.path - 96, 140, 12, [1, 0, .35]); rect(X - 70, PARK.path - 76, 140, 10, [1, 0, .35]); rect(X - 60, PARK.path - 66, 8, 30, [1, 0, .35]); rect(X + 52, PARK.path - 66, 8, 30, [1, 0, .35]); rect(X - 70, PARK.path - 130, 140, 10, [1, 0, .35]); }
  }
  // falling petals (pink overprint)
  over(() => {
    const R = mulberry(9);
    for (let i = 0; i < 60; i++) {
      const x0 = R() * 2400, sp = 30 + R() * 50, ph = R() * 10;
      const X = ((x0 - cx * .8 - t * sp + Math.sin(t * 1.3 + ph) * 30) % 2400 + 2400) % 2400 - 240;
      const Y = ((R() * 900 + t * (40 + R() * 40)) % 900) + 80;
      g.save(); g.translate(X, Y); g.rotate(t * 2 + ph); g.beginPath(); g.ellipse(0, 0, 7, 4, 0, 0, 7); g.fillStyle = inkA([0, 0, .9]); g.fill(); g.restore();
    }
  });
}
// foreground cherry blossoms (drawn in front of the characters, parallax 1.4)
export function parkFore(cx, t) {
  for (let k = -1; k < 5; k++) { const X = k * 1500 + 1700 - cx * 1.4; if (X < -500 || X > W + 500) continue; blossom(X, H + 160, 1.5, 300 + k, t); }
}

// ───────── Top-down: embankment (straight overhead) ─────────
// World 1920×1080: top = river, middle = coping stones, bottom = walkway. The sun is low over the river at top right, so shadows stretch long toward bottom left
export function overhead(o = {}) {
  const t = o.t || 0, SH = [.55, 0, .06];
  rect(0, 0, W, 500, [.22, .85, 0]);
  const R = mulberry(5);
  for (let i = 0; i < 34; i++) { const yy = R() * 480, xx = ((R() * 2400 + t * 14) % 2400) - 240, ww = 40 + R() * 160; rect(xx, yy, ww, 4 + R() * 4, [.75, .5, 0]); }
  for (let i = 0; i < 22; i++) { const xx = 1500 + (R() - .5) * 600 + Math.sin(t * 2 + i) * 10, yy = 40 + R() * 400; ellipse(xx, yy, 26 + R() * 50, 5 + R() * 5, 0, [0, .1, 1]); }
  // coping stones
  rect(0, 500, W, 130, [.4, 0, .6]);
  for (let k = 0; k < 12; k++) rect(k * 180 + 60, 500, 5, 130, [.8, 0, .7]);
  rect(0, 500, W, 7, [.8, 0, .7]); rect(0, 624, W, 7, [.8, 0, .7]);
  // walkway
  rect(0, 631, W, H - 631, [0, .2, .1]);
  for (let r = 0; r < 8; r++) for (let k = 0; k < 20; k++) { if (hash(r * 31 + k * 7) > .3) continue; rect(k * 110 + (r % 2) * 55, 660 + r * 52, 60, 3, [.2, .3, .1]); }
  // ── shadows (blue overprint) ──
  const man = [930, 566], bk = [560, 660];
  over(() => {
    g.fillStyle = inkA(SH); g.strokeStyle = inkA(SH);
    // person's shadow: stretches from under the body toward bottom left, head shadow at the end
    g.beginPath(); g.moveTo(man[0] - 60, 640); g.lineTo(man[0] - 440, 1000); g.lineTo(man[0] - 330, 1040); g.lineTo(man[0] + 40, 640); g.closePath(); g.fill();
    g.beginPath(); g.ellipse(man[0] - 400, 1040, 80, 56, -.7, 0, 7); g.fill();
    // bike shadow: wheels become long slanted ellipses, the frame is a few lines
    const dx = -250, dy = 330;
    g.lineWidth = 12;
    const wA = [bk[0] - 150 + dx, bk[1] + dy], wB = [bk[0] + 150 + dx * .8, bk[1] + dy * .8];
    for (const w of [wA, wB]) { g.beginPath(); g.ellipse(w[0], w[1], 118, 64, -.72, 0, 7); g.stroke(); }
    g.lineWidth = 9;
    g.beginPath(); g.moveTo(wA[0], wA[1]); g.lineTo(wA[0] + 120, wA[1] - 80); g.lineTo(wB[0], wB[1]); g.moveTo(wA[0] + 120, wA[1] - 80); g.lineTo(wA[0] + 60, wA[1] - 150); g.moveTo(wB[0], wB[1]); g.lineTo(wB[0] + 10, wB[1] - 130); g.stroke();
    // pigeon shadows
    g.beginPath(); g.ellipse(1150 - 150, 700, 80, 24, -.75, 0, 7); g.fill();
  });
  // ── bicycle (leaning on the parapet; seen from above = a long thin strip) ──
  const [bx, by] = bk;
  rrect(bx - 250, by - 7, 200, 14, 7, [1, 0, .55]); rrect(bx + 50, by - 7, 200, 14, 7, [1, 0, .55]);
  line([[bx - 150, by], [bx + 150, by]], 14, [.72, 0, 1]);
  line([[bx + 140, by - 46], [bx + 140, by + 46]], 10, [.35, 0, 0]);
  circle(bx + 140, by - 46, 8, [.3, 0, 0]); circle(bx + 140, by + 46, 8, [.3, 0, 0]);
  rrect(bx + 158, by - 38, 90, 76, 8, PAL.basket); for (let k = 0; k < 4; k++) line([[bx + 162, by - 30 + k * 20], [bx + 244, by - 30 + k * 20]], 3, PAL.weave);
  rrect(bx - 150, by - 16, 56, 32, 14, PAL.saddle);
  // ── person (sitting on the coping stones, legs stretched toward the river) ──
  const [mx, my] = man;
  line([[mx - 28, my - 10], [mx - 34, my - 150]], 40, PAL.trousersSh); line([[mx + 28, my - 10], [mx + 32, my - 150]], 40, PAL.trousers);
  ellipse(mx - 34, my - 160, 20, 14, 0, PAL.shoe); ellipse(mx + 32, my - 160, 20, 14, 0, PAL.shoe);
  // scarf tail trailing behind
  curve([[mx - 10, my + 30], [mx - 40, my + 80], [mx - 26, my + 130], [mx - 60, my + 175]], 26, PAL.scarf);
  ellipse(mx, my + 20, 82, 58, 0, PAL.stripeA);
  // arms: right hand offers half the baguette to the pigeons, left hand holds the other half
  line([[mx + 60, my + 10], [mx + 150, my - 20]], 30, PAL.stripeA); circle(mx + 160, my - 22, 15, PAL.skin);
  baguette(mx + 196, my - 26, 90, -.1, { half: true, r: 15 });
  line([[mx - 60, my + 10], [mx - 90, my - 40]], 30, PAL.sweaterSh); circle(mx - 92, my - 48, 15, PAL.skin);
  baguette(mx - 100, my - 80, 80, -1.3, { half: true, r: 14 });
  rrect(mx - 40, my - 20, 80, 30, 14, PAL.scarf);
  circle(mx, my - 16, 42, PAL.hair);
  line([[mx - 18, my - 50], [mx + 4, my - 60]], 6, [1, 0, .5]);
  // ── pigeons (top view) ──
  const px = 1175, py = 552;
  ellipse(px, py, 60, 36, 0, PAL.pigeon); ellipse(px + 4, py, 38, 30, 0, PAL.pigeonWing);
  poly([[px + 54, py - 16], [px + 96, py - 10], [px + 96, py + 10], [px + 54, py + 16]], PAL.pigeonSh);
  circle(px - 52, py, 20, PAL.pigeonNeck); circle(px - 64, py, 15, PAL.pigeon); poly([[px - 76, py - 5], [px - 92, py], [px - 76, py + 5]], PAL.beak);
}

// ───────── Printer output tray (top view) + paper stack ─────────
export function printerTable() {
  rect(0, 0, W, H, [.28, .32, .12]);                     // table top
  for (let i = 0; i < 18; i++) rect(0, i * 62 + 20, W, 3, [.36, .38, .16]);
}
export function printerBody(sh) {                          // machine (drawn over the paper, output slot on its bottom edge)
  rect(0, 0, W, sh, [.75, 0, .2]);
  rect(0, sh - 30, W, 30, [1, 0, .35]);
  rect(W / 2 - 700, sh - 12, 1400, 12, [.2, 0, 0]);       // output slot
  rrect(160, 60, 380, sh - 140, 16, [.5, 0, .1]);
  for (let k = 0; k < 4; k++) circle(240 + k * 80, 120, 22, k === 0 ? [0, .2, 1] : [1, 0, .3]);
  rrect(1300, 60, 460, 90, 10, [.2, .5, .1]);
  text('1 · 2 · 3', 1530, 118, '700 40px Jost', [1, 0, .3], 'center', 'alphabetic', 6);
  for (let k = 0; k < 3; k++) rrect(1330 + k * 150, 180, 110, 40, 8, [[1, 0, 0], [0, 1, 0], [0, 0, 1]][k]);
}
export function paperSheet(x, y, w, h, rot, fn) {          // one sheet: paper white + thin edge + content (fn draws the content in a 1920×1080 world)
  g.save(); g.translate(x, y); g.rotate(rot);
  rect(-w / 2 - 3, -h / 2 - 3, w + 6, h + 6, [.3, .1, .1]);
  rect(-w / 2, -h / 2, w, h, [0, 0, 0]);
  if (fn) {
    const m = w * .035, k = (w - 2 * m) / W;
    g.save(); g.beginPath(); g.rect(-w / 2 + m, -h / 2 + m, w - 2 * m, h - 2 * m); g.clip();
    g.translate(-w / 2 + m, -h / 2 + m); g.scale(k, k * ((h - 2 * m) / (H * k)));
    fn();
    g.restore();
  }
  g.restore();
}

// ───────── Bike-bell close-up ─────────
export function bellECU(t, rg) {
  // background: early-morning blue + lamp posts whipping past and road speed lines (sense of motion)
  rect(0, 0, W, H, [.16, .1, 0]);
  rect(0, 820, W, 260, [.3, .06, .04]);
  for (let k = 0; k < 14; k++) { const yy = 850 + k * 17, X = ((k * 373 - t * 3000) % 2600 + 2600) % 2600 - 400; rect(X, yy, 260 + (k % 3) * 120, 4, [.6, 0, .1]); }
  for (let k = 0; k < 6; k++) { const X = ((k * 560 - t * 2600) % 3360 + 3360) % 3360 - 400; rect(X, 0, 46, 820, [.45, 0, .1]); }
  const shake = rg > 0 ? Math.sin(rg * 95) * 7 * Math.exp(-rg * 3.5) : 0;
  const bob = Math.sin(t * 9) * 3;
  g.save(); g.translate(0, bob);
  // handlebar (thick tube crossing the frame diagonally)
  line([[-80, 760], [W + 80, 610]], 84, [.8, 0, .15]);
  line([[-80, 734], [W + 80, 584]], 10, [0, 0, 0]);
  // stem (exits frame bottom right)
  line([[1560, 640], [1620, H + 60]], 96, [.8, 0, .15]);
  // bell clamp
  rrect(1080, 580, 120, 90, 14, [1, 0, .25]);
  // bell body
  const bx = 1140 + shake, by = 420;
  ellipse(bx, by + 150, 250, 64, 0, [.55, 0, .1]);
  g.beginPath(); g.moveTo(bx - 250, by + 150); g.bezierCurveTo(bx - 250, by - 150, bx + 250, by - 150, bx + 250, by + 150); g.closePath(); g.fillStyle = inkA([1, 0, .25]); g.fill();
  g.save(); g.translate(bx - 95, by + 5); g.rotate(-.5); g.beginPath(); g.ellipse(0, 0, 70, 30, 0, 0, 7); g.fillStyle = inkA([0, 0, 0]); g.fill(); g.restore();
  circle(bx + 40, by - 70, 14, [0, 0, 0]);
  circle(bx, by - 78, 26, [.7, 0, .15]); circle(bx, by - 78, 10, [1, 0, .25]);
  ellipse(bx, by + 150, 250, 64, 0, [.8, 0, .2]); ellipse(bx, by + 142, 226, 48, 0, [1, 0, .25]);
  g.restore();
  // lever + hand (skin is paper white on the blue-only plate → give it a blue outline in the close-up)
  const flick = rg > 0 && rg < .3 ? Math.sin(rg / .3 * Math.PI) : 0;
  g.save(); g.translate(0, bob);
  g.save(); g.translate(930, 600); g.rotate(-.25 - flick * .45); rrect(-150, -16, 170, 32, 16, [.8, 0, .15]); circle(-150, 0, 22, [.8, 0, .15]); g.restore();
  line([[-200, 1000], [300, 760]], 190, PAL.stripeA);
  rrect(250, 660, 90, 200, 30, PAL.rib);
  const hand = () => { g.beginPath(); g.moveTo(330, 640); g.bezierCurveTo(420, 600, 580, 610, 640, 660); g.bezierCurveTo(680, 720, 640, 820, 560, 830); g.bezierCurveTo(460, 840, 360, 830, 320, 790); g.closePath(); };
  hand(); g.lineWidth = 12; g.strokeStyle = inkA([1, 0, .2]); g.stroke(); g.fillStyle = inkA(PAL.skin); g.fill();
  for (let k = 0; k < 3; k++) line([[430 + k * 60, 700], [440 + k * 60, 820]], 6, PAL.skinSh);
  g.save(); g.translate(600, 650); g.rotate(-.35 - flick * .5);
  g.beginPath(); g.roundRect(-20, -26, 200, 52, 26); g.lineWidth = 12; g.strokeStyle = inkA([1, 0, .2]); g.stroke(); g.fillStyle = inkA(PAL.skin); g.fill();
  line([[150, -14], [150, 14]], 5, PAL.skinSh);
  g.restore();
  g.restore();
  // vibration lines (alternating on twos)
  if (rg > 0 && rg < 1.0) {
    const k = Math.floor(rg * 12) % 2;
    for (let i = 0; i < 3; i++) { const r = 300 + i * 56 + k * 16; g.lineWidth = 12; g.strokeStyle = inkA([1, 0, .2]); g.beginPath(); g.arc(1140, 460, r, -1.15, -.35); g.stroke(); g.beginPath(); g.arc(1140, 460, r, Math.PI + .35, Math.PI + 1.15); g.stroke(); }
  }
}

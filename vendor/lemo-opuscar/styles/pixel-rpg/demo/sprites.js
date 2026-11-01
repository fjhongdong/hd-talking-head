// sprites.js — character rig (capsule limbs + stepped shading by light direction + automatic outline) + hand-drawn ASCII heads
import { C, T, sprFromRows } from './px.js';

// —— Material tone steps [line, dark, mid, light] ——
export const MAT = {
  skin: [C.brown, C.skinS, C.skin, C.sand],
  hairA: [C.umber, C.umber, C.dbrown, C.brown],
  tunicA: [C.ink, C.night, C.navy, C.blue],
  steel: [C.night, C.slate, C.steel, C.silver],
  leather: [C.umber, C.umber, C.dbrown, C.brown],
  pants: [C.ink, C.night, C.dslate, C.slate],
  boots: [C.ink, C.umber, C.dbrown, C.brown],
  gold: [C.dbrown, C.brown, C.amber, C.yellow],
  scarf: [C.umber, C.scarfD, C.scarf, C.scarfL],
  hairW: [C.umber, C.dbrown, C.rust, C.clay],
  cloakW: [C.teal, C.dgreen, C.green, C.lime],
  tunicW: [C.brown, C.tan, C.sand, C.white],
  wood: [C.umber, C.dbrown, C.brown, C.tan],
  glow: [C.orange, C.orange, C.amber, C.yellow],
  blade: [C.dslate, C.steel, C.silver, C.white],
};
const L = [-.55, -.83];                         // light comes from the upper left

// —— ASCII heads (no outer outline; the global outline pass adds it) ——
// h/H/j hair mid/light/dark, f/F skin light/dark, e eye (ink), w eye white, b brow (dark hair), m mouth
const HEADS_A = {
  side: [
    '......jjjj....',
    '...jjhhhhhhj..',
    '..jhhHHHHHhhj.',
    '.jhHHHHHHHHhhj',
    'jjhHHhhhhhhhhh',
    '.jjhhhhhhhhhhh',
    '..jhhhhhhjhjhh',
    '.jjhhhhhjffhff',
    'jjhhhhhFfffbbf',
    '.jjhhhFFfffeff',
    '..jhhhFffffeff',
    '..jjhhhFfffff.',
    '....jjFffffmf.',
    '......FFfff...',
  ],
  up: [
    '.....jjjj.....',
    '..jjhhhhhhj...',
    '.jhhHHHHHhhj..',
    'jhHHHHHHHHhhj.',
    'jhHHhhhhhhhhhh',
    'jjhhhhhhhhhjhf',
    '.jjhhhhhjfhbbf',
    '..jhhhhhFfffef',
    '.jjhhhFFffffef',
    'jjhhhhFfffffff',
    '.jjhhhhFffffff',
    '..jjjhFFffmff.',
    '....jFFffff...',
    '......FF......',
  ],
  down: [
    '..............',
    '......jjjj....',
    '...jjhhhhhhj..',
    '..jhhHHHHHhhj.',
    '.jhHHHHHHHHhhj',
    'jjhHHhhhhhhhhh',
    '.jjhhhhhhhhhhh',
    '..jhhhhhhjhjhh',
    '.jjhhhhhjfbbhf',
    'jjhhhhhFffffFf',
    '.jjhhhFFfffeff',
    '..jhhhFffffmff',
    '..jjhhhFffff..',
    '....jjFFff....',
  ],
  front: [
    '...jj.jj.jj...',
    '..jhhjhhjhhj..',
    '.jhHHHHHHHHhj.',
    'jhHHHhhhhhHhhj',
    'jhhhhhhhhhhhhj',
    'jhhjhhhjhhjhhj',
    'jhhfjhffhjffhj',
    'jhfbbffffbbfhj',
    'Fhfewffffwefhf',
    'FFfeFffffFefFF',
    '.FFfffffffffF.',
    '..FFfffmfffF..',
    '...FFFffffF...',
    '.....FFFF.....',
  ],
  back: [
    '...jj.jj.jj...',
    '..jhhjhhjhhj..',
    '.jhHHHHHHHHhj.',
    'jhHHHHhhhhhhhj',
    'jhhhhhhhhhhhhj',
    'jhhhhhhhhhhhhj',
    'jjhhhhhhhhhhjj',
    'jjhhhhhhhhhhjj',
    'Fjjhhhhhhhhjjf',
    'FFjjhhhhhhjjFF',
    '.FjjjhjjhjjjF.',
    '..FFjjjjjjFF..',
    '...FFFFFFFF...',
    '.....FFFF.....',
  ],
};
const HEADS_W = {
  side: [
    '....jjhhhj....',
    '..jhhHHHHhhj..',
    '.jhHHHHHHHhhj.',
    'jhHHHhhhhhhhhh',
    'jhhhhhhhhhhhhh',
    'jhhhhhhhhjhhhf',
    'jhhhhhhhjfhfff',
    'jhhhhhhFfffbbf',
    'jhhhhhFFfffeef',
    'hjjhhhFfFffwef',
    'hhjjhhFFffffff',
    'jhhjjhFFfffmf.',
    '.jhj..FFffff..',
    '..j....FFF....',
  ],
  down: [
    '..............',
    '....jjhhhj....',
    '..jhhHHHHhhj..',
    '.jhHHHHHHHhhj.',
    'jhHHHhhhhhhhhh',
    'jhhhhhhhhhhhhh',
    'jhhhhhhhhjhhhf',
    'jhhhhhhhjfhfff',
    'jhhhhhhFfffbbf',
    'jhhhhhFFffffFf',
    'hjjhhhFfFfffef',
    'hhjjhhFFfffmf.',
    'jhhjjhFFffff..',
    '.jhj...FFF....',
  ],
  front: [
    '....jjhhjj....',
    '..jhhHHHHhhj..',
    '.jhHHHHHHHHhj.',
    'jhHHhhhhhhHhhj',
    'jhhhhhhhhhhhhj',
    'jhhjhhhhhjhhhj',
    'jhhffhffhffhhj',
    'jhfbbffffbbfhj',
    'jhfeeffffeefhj',
    'jhfwefffffwfhj',
    'jhFfffffffffhj',
    'jhhFFffmffFhhj',
    'jhh.FFFFFF.hhj',
    '.jj........jj.',
  ],
};
export function headSprite(rows, hairMat) {
  const hm = MAT[hairMat], sk = MAT.skin;
  return sprFromRows(rows, { h: hm[2], H: hm[3], j: hm[1], f: sk[2], F: sk[1], e: C.ink, w: C.white, b: hm[1], m: sk[0] });
}

// —— Rig drawing ——
// Canvas 48×48, origin (centre of the feet) at (24,44)
const SW = 48, SH = 48, OX = 24, OY = 44;
class Buf {
  constructor() { this.m = new Int16Array(SW * SH).fill(-1); this.part = new Int16Array(SW * SH).fill(-1); this.np = 0; this.lineMask = new Uint8Array(SW * SH); }
  // Layer a part on (pixel set + per-pixel tone step); draw an inner outline where it meets parts already there
  stamp(pix, mat) {
    const id = this.np++, set = new Set(pix.map(p => p.i));
    for (const p of pix) {
      const x = p.i % SW, y = (p.i / SW) | 0;
      let edgeOnOther = false;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const X = x + dx, Y = y + dy; if (X < 0 || Y < 0 || X >= SW || Y >= SH) continue;
        const j = Y * SW + X; if (!set.has(j) && this.part[j] >= 0 && this.part[j] !== id) edgeOnOther = true;
      }
      const tn = this.flat && p.tone === 3 ? 2 : p.tone;
      this.m[p.i] = edgeOnOther && mat.line !== false ? MAT[mat.name][0] : MAT[mat.name][tn];
      this.part[p.i] = id;
    }
  }
  raw(x, y, c) { x = Math.round(x) + OX; y = Math.round(y) + OY; if (x < 0 || y < 0 || x >= SW || y >= SH) return; this.m[y * SW + x] = c; this.part[y * SW + x] = 999; }
  sprite(spr, x0, y0, flip = false) {
    for (let y = 0; y < spr.h; y++) for (let x = 0; x < spr.w; x++) {
      const c = spr.d[y * spr.w + (flip ? spr.w - 1 - x : x)]; if (c === T) continue;
      const X = x0 + x + OX, Y = y0 + y + OY; if (X < 0 || Y < 0 || X >= SW || Y >= SH) continue;
      this.m[Y * SW + X] = c; this.part[Y * SW + X] = 998;
    }
  }
  finish(outline = C.ink) {
    const d = new Uint8Array(SW * SH).fill(T);
    for (let i = 0; i < d.length; i++) if (this.m[i] >= 0) d[i] = this.m[i];
    const o = d.slice();
    for (let y = 0; y < SH; y++) for (let x = 0; x < SW; x++) {
      const i = y * SW + x; if (d[i] !== T) continue;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const X = x + dx, Y = y + dy; if (X >= 0 && Y >= 0 && X < SW && Y < SH && d[Y * SW + X] !== T) { o[i] = outline; break; } }
    }
    return { w: SW, h: SH, d: o, ox: OX, oy: OY };
  }
}
function toneOf(nx, ny, ramp = [.38, -.28]) { const v = nx * L[0] + ny * L[1]; return v > ramp[0] ? 3 : v < ramp[1] ? 1 : 2; }
// Capsule: a→b, radius r0→r1; shading by the cross-section normal
function capsule(x0, y0, x1, y1, r0, r1 = r0, bias = 0) {
  const pix = [], dx = x1 - x0, dy = y1 - y0, len = Math.hypot(dx, dy) || 1e-6, ux = dx / len, uy = dy / len, px_ = -uy, py_ = ux;
  const R = Math.max(r0, r1) + 1;
  for (let y = Math.floor(Math.min(y0, y1) - R); y <= Math.ceil(Math.max(y0, y1) + R); y++) for (let x = Math.floor(Math.min(x0, x1) - R); x <= Math.ceil(Math.max(x0, x1) + R); x++) {
    const cx = x + .5 - .5, cy = y;                  // pixel centre
    const t = Math.max(0, Math.min(1, ((cx - x0) * ux + (cy - y0) * uy) / len)), qx = x0 + ux * len * t, qy = y0 + uy * len * t;
    const r = r0 + (r1 - r0) * t, d = Math.hypot(cx - qx, cy - qy); if (d > r + .15) continue;
    const s = ((cx - qx) * px_ + (cy - qy) * py_) / Math.max(.6, r), nx = px_ * s, ny = py_ * s;
    const X = x + OX, Y = y + OY; if (X < 0 || Y < 0 || X >= SW || Y >= SH) continue;
    pix.push({ i: Y * SW + X, tone: toneOf(nx + bias * L[0], ny + bias * L[1]) });
  }
  return pix;
}
// Polygon (scanline), shading by a pseudo-normal toward the centre
function poly(pts, cx, cy, rx, ry, ramp) {
  const pix = []; let y0 = Infinity, y1 = -Infinity; for (const [, y] of pts) { y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  for (let y = Math.floor(y0); y <= Math.ceil(y1); y++) {
    const xs = []; const yc = y + .0;
    for (let i = 0; i < pts.length; i++) { const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length]; if ((ay <= yc && by > yc) || (by <= yc && ay > yc)) xs.push(ax + (yc - ay) / (by - ay) * (bx - ax)); }
    xs.sort((a, b) => a - b);
    for (let k = 0; k + 1 < xs.length; k += 2) for (let x = Math.round(xs[k]); x < Math.round(xs[k + 1]); x++) {
      const X = x + OX, Y = y + OY; if (X < 0 || Y < 0 || X >= SW || Y >= SH) continue;
      pix.push({ i: Y * SW + X, tone: toneOf((x + .5 - cx) / rx, (y + .5 - cy) / ry, ramp) });
    }
  }
  return pix;
}
function disc(cx, cy, r) { const pix = []; for (let y = Math.floor(cy - r - 1); y <= cy + r + 1; y++) for (let x = Math.floor(cx - r - 1); x <= cx + r + 1; x++) { const dx = x - cx, dy = y - cy; if (dx * dx + dy * dy > r * r + .3) continue; const X = x + OX, Y = y + OY; if (X < 0 || Y < 0 || X >= SW || Y >= SH) continue; pix.push({ i: Y * SW + X, tone: toneOf(dx / (r || 1), dy / (r || 1)) }); } return pix; }
const rot = (a, x, y) => [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
// Limb forward kinematics: from the root, angle 0 = straight down, positive = forward (+x)
function limb(root, a1, l1, a2, l2) {
  const k = [root[0] + Math.sin(a1) * l1, root[1] + Math.cos(a1) * l1];
  const e = [k[0] + Math.sin(a1 - a2) * l2, k[1] + Math.cos(a1 - a2) * l2];
  return [k, e];
}

// Ahoge: one tuft of hair sticking up (dir 1 = curls forward, 0 = front/back view), sways with the step over 2 frames
function ahoge(b, x, y, dir, t) {
  const sw = Math.floor(t * 8) % 2;
  const hc = MAT.hairA;
  if (dir === 0) { b.raw(x, y - 1, hc[2]); b.raw(x, y - 2, hc[2]); b.raw(x + 1 - sw, y - 3, hc[3]); b.raw(x + 2 - sw, y - 3, hc[2]); return; }
  b.raw(x, y - 1, hc[2]); b.raw(x + dir * sw * 0, y - 2, hc[2]); b.raw(x + dir, y - 3, hc[3]); b.raw(x + dir * 2, y - 3 + sw, hc[2]);
}
// —— Character definitions ——
export const CHARS = {
  arlo: { heads: HEADS_A, hair: 'hairA', tunic: 'tunicA', h: 1, scarf: true, sword: true },
  wren: { heads: HEADS_W, hair: 'hairW', tunic: 'cloakW', h: 0, scarf: true, staff: true, cloak: false, dress: true },
};
const headCache = new Map();
function head(ch, kind) { const k = ch + kind; if (!headCache.has(k)) headCache.set(k, headSprite(CHARS[ch].heads[kind] || CHARS[ch].heads.side, CHARS[ch].hair)); return headCache.get(k); }

// Pose: { by body drop, lean torso lean forward, legF:[a1,a2], legB, armF:[a1,a2], armB, head:'side'|'up'|..., item: 'sword'|'staff'|null, scarfWrap }
export const POSE = {
  idle: { by: 0, lean: 0, legF: [.12, 0], legB: [-.1, 0], armF: [-.05, -.25], armB: [.1, -.2], head: 'side' },
  breathe: { by: 0, lean: 0, rise: 1, legF: [.12, 0], legB: [-.1, 0], armF: [-.1, -.2], armB: [.12, -.15], head: 'side' },
  walk0: { by: 0, legF: [.48, .12], legB: [-.42, .3], armF: [-.4, -.35], armB: [.4, -.3], head: 'side' },
  walk1: { by: -1, legF: [.05, .05], legB: [.3, 1.0], armF: [0, -.3], armB: [0, -.25], head: 'side' },
  walk2: { by: 0, legF: [-.42, .3], legB: [.48, .12], armF: [.4, -.35], armB: [-.4, -.3], head: 'side' },
  walk3: { by: -1, legF: [.3, 1.0], legB: [.05, .05], armF: [0, -.3], armB: [0, -.25], head: 'side' },
  ready: { by: 1, lean: .12, legF: [.5, .4], legB: [-.45, .15], armF: [.55, .75], armB: [.35, .8], head: 'side', item: 'held' },
  attack: { by: 1, lean: .3, legF: [.75, .5], legB: [-.55, .1], armF: [1.75, .15], armB: [-.3, -.5], head: 'side', item: 'swing' },
  hurt: { by: 1, lean: -.38, legF: [.55, .9], legB: [-.2, .2], armF: [-1.3, -.5], armB: [-1.1, -.4], head: 'up', blink: true },
  lookup: { by: 0, lean: -.08, legF: [.12, 0], legB: [-.1, 0], armF: [.05, -.35], armB: [.1, -.2], head: 'up' },
  push: { by: 1, lean: .45, legF: [.35, .25], legB: [-.7, .15], armF: [1.45, .25], armB: [1.3, .3], head: 'side' },
  grip: { by: 0, lean: 0, legF: [.12, 0], legB: [-.1, 0], armF: [.35, 2.25], armB: [.1, -.2], head: 'down' },
  cast: { by: 0, lean: .05, legF: [.3, .1], legB: [-.25, .1], armF: [1.9, .3], armB: [.3, -.5], head: 'side', item: 'raise' },
  kneel: { by: 5, lean: .32, legF: [1.5, 1.5], legB: [.1, 1.7], armF: [.5, .3], armB: [.3, .1], head: 'down' },
  sit: { by: 6, lean: .04, legF: [1.55, 1.5], legB: [1.4, 1.45], armF: [.55, .9], armB: [.45, .8], head: 'side' },
  sitlean: { by: 6, lean: -.12, legF: [1.55, 1.5], legB: [1.4, 1.45], armF: [.3, .6], armB: [.45, .8], head: 'down' },
  front: { view: 'front' }, back: { view: 'back' },
  backlook: { view: 'back', headUp: 1 }, backbreathe: { view: 'back', rise: 1 },
  backpush: { view: 'back', arms: 'push', lean: 1 }, backwalk0: { view: 'back', legL: -1 }, backwalk1: { view: 'back', legR: -1 },
};

// Generate a character frame. opts: {scarf:bool, wind:0..1, t:phase}
export function drawChar(ch, poseName, opts = {}) {
  const P = POSE[poseName], D = CHARS[ch], b = new Buf(); b.flat = !!opts.flat;
  if (P.view) return drawFrontBack(ch, P.view, opts, P);
  const H0 = D.h;                                     // height difference (ARLO is 1 taller)
  const by = P.by || 0, lean = P.lean || 0, rise = P.rise || 0;
  const hip = [0, -12 - H0 + by];
  const [shx, shy] = rot(lean, 0, -8 - rise); const sh = [hip[0] + shx, hip[1] + shy];
  const neck = [sh[0] + rot(lean, 0, -1.5)[0] + .5, sh[1] - 1.5];
  const tunic = D.tunic;
  // Back layer: sword (on the back) / cloak
  if (D.cloak) {
    const sway = Math.sin((opts.t || 0) * 5) * (opts.wind || .4);
    b.stamp(poly([[sh[0] - 1, sh[1] - 1], [sh[0] + 1.5, sh[1]], [hip[0] - 1, hip[1] + 7], [hip[0] - 7 - sway * 2, hip[1] + 8], [hip[0] - 6 - sway, hip[1] + 1]], hip[0] - 3, hip[1] - 2, 5, 8), { name: 'cloakW' });
  }
  // Back arm, back leg (darkened one step overall: bias pushes toward shadow)
  const legLen = [6, 6];
  const [kB, aB] = limb(hip, P.legB[0], legLen[0], P.legB[1], legLen[1]);
  b.stamp(capsule(hip[0] - .5, hip[1], kB[0], kB[1], 1.7, 1.4, -.6), { name: 'pants' });
  b.stamp(capsule(kB[0], kB[1], aB[0], aB[1], 1.5, 1.4, -.6), { name: 'boots' });
  b.stamp(capsule(aB[0], aB[1], aB[0] + 2.2 * Math.cos(P.legB[0] - P.legB[1]), aB[1] - 2.2 * Math.sin(P.legB[0] - P.legB[1]) * 0, 1.2, 1.1, -.6), { name: 'boots' });
  const [eB, hB] = limb(sh, P.armB[0], 4.5, P.armB[1], 4.5);
  b.stamp(capsule(sh[0], sh[1] + .5, eB[0], eB[1], 1.3, 1.2, -.7), { name: tunic });
  b.stamp(capsule(eB[0], eB[1], hB[0], hB[1], 1.1, 1.1, -.7), { name: ch === 'arlo' ? 'leather' : 'skin' });
  if (D.staff && P.item !== 'raise') {          // staff held in the back hand: the staff is behind the body
    const bot = [hB[0] + 1.5, -1 + Math.min(0, (P.by || 0) - 3)], top = [bot[0] + 3, bot[1] - 31 + (P.by || 0)];
    b.stamp(capsule(bot[0], bot[1], top[0], top[1], .7, .7, -.5), { name: 'wood' });
    b.stamp(disc(top[0], top[1] - 1, 1.6), { name: 'glow' });
  }
  // Torso + hem
  const [hx1, hy1] = rot(lean, 3.4, -8), [hx0, hy0] = rot(lean, -3.6, -8);
  const flare = D.dress ? 5.2 : 4.2, hem = D.dress ? 5.5 : 3.5;
  b.stamp(poly([[hip[0] + hx0, hip[1] + hy0 - rise], [hip[0] + hx1, hip[1] + hy1 - rise], [hip[0] + flare, hip[1] + hem], [hip[0] - flare - .5, hip[1] + hem]], hip[0] - .5 + rot(lean, 0, -4)[0], hip[1] - 4, 4.2, 6.5), { name: tunic });
  // Belt
  const beltY = hip[1] - 1;
  b.stamp(poly([[hip[0] - 4.2, beltY - 1], [hip[0] + 4, beltY - 1], [hip[0] + 4.2, beltY + 1], [hip[0] - 4.4, beltY + 1]], hip[0], beltY, 5, 3), { name: 'leather' });
  b.raw(hip[0] + 2.6, beltY - .5, C.amber); b.raw(hip[0] + 2.6, beltY + .5, C.brown);
  if (D.sword && P.item !== 'held' && P.item !== 'swing') {   // sword at the hip: scabbard slants back and down, hilt in front
    b.stamp(capsule(hip[0] + 1, hip[1] - .5, hip[0] - 7, hip[1] + 4.5, .9, .8), { name: 'leather' });
    b.raw(hip[0] - 7, hip[1] + 4.5, C.amber);
    b.stamp(capsule(hip[0] + 1.5, hip[1] - 1.5, hip[0] + 4, hip[1] - 3.2, .6), { name: 'steel' });
    b.raw(hip[0] + 1.5, hip[1] - .5, C.amber); b.raw(hip[0] + 1.5, hip[1] - 2.5, C.amber);
  }
  // Front leg
  const [kF, aF] = limb(hip, P.legF[0], legLen[0], P.legF[1], legLen[1]);
  b.stamp(capsule(hip[0] + .5, hip[1], kF[0], kF[1], 1.7, 1.4), { name: 'pants' });
  b.stamp(capsule(kF[0], kF[1], aF[0], aF[1], 1.5, 1.4), { name: 'boots' });
  b.stamp(capsule(aF[0], aF[1], aF[0] + 2.4, aF[1], 1.2, 1.1), { name: 'boots' });
  // Scarf wrapped round the neck (the tail is drawn procedurally by the scene)
  // Head
  const hk = P.head || 'side', hs = head(ch, hk);
  const hx = Math.round(neck[0] - 6), hy = Math.round(neck[1] - 13);
  b.sprite(hs, hx, hy);
  if (ch === 'arlo') ahoge(b, hx + 8, hy, hk === 'up' ? -1 : 1, opts.t || 0);
  if (opts.scarf ?? D.scarf) {
    const sy = Math.round(neck[1]) - 1;
    b.stamp(poly([[neck[0] - 3.5, sy - 1], [neck[0] + 3, sy - 1.5], [neck[0] + 3.5, sy + 1.5], [neck[0] - 3.5, sy + 1.5]], neck[0] - 1, sy - 2, 4, 3), { name: 'scarf' });
  }
  // Pauldron (ARLO)
  if (ch === 'arlo') b.stamp(disc(sh[0] - .5, sh[1] + 1, 2.3), { name: 'steel' });
  // Front arm
  const [eF, hF] = limb(sh, P.armF[0], 4.5, P.armF[1], 4.5);
  b.stamp(capsule(sh[0], sh[1] + .5, eF[0], eF[1], 1.4, 1.2), { name: tunic });
  b.stamp(capsule(eF[0], eF[1], hF[0], hF[1], 1.2, 1.1), { name: ch === 'arlo' ? 'steel' : 'skin' });
  b.stamp(disc(hF[0], hF[1], 1.1), { name: ch === 'arlo' ? 'leather' : 'skin' });
  // Held item
  if (P.item === 'held' || P.item === 'swing') {
    const a = P.item === 'swing' ? .25 : -.55, len = 12, ca = Math.cos(a), sa = Math.sin(a);
    b.stamp(capsule(hF[0] + ca * 1.5, hF[1] + sa * 1.5, hF[0] + ca * len, hF[1] + sa * len, .8, .55), { name: 'blade', line: false });
    b.stamp(capsule(hF[0] + ca * 1.5 - sa * 2, hF[1] + sa * 1.5 + ca * 2, hF[0] + ca * 1.5 + sa * 2, hF[1] + sa * 1.5 - ca * 2, .55), { name: 'gold' });
  }
  if (D.staff && P.item === 'raise') {
    const bot = [hF[0] - 2, hF[1] + 8], dir = [.45, -1], n = Math.hypot(dir[0], dir[1]), len = 20;
    const top = [bot[0] + dir[0] / n * len, bot[1] + dir[1] / n * len];
    b.stamp(capsule(bot[0], bot[1], top[0], top[1], .7), { name: 'wood' });
    b.stamp(disc(top[0], top[1] - 1, 1.6), { name: 'glow' });
    b.stamp(disc(hF[0], hF[1], 1.1), { name: 'skin' });
  }
  return b.finish();
}
function drawFrontBack(ch, view, opts, P = {}) {
  const D = CHARS[ch], b = new Buf(), H0 = D.h, tunic = D.tunic, rise = P.rise || 0, lean = P.lean || 0;
  const hip = [0, -12 - H0], sh = [0, -20 - H0 - rise + lean];
  const lL = P.legL || 0, lR = P.legR || 0;
  if (D.cloak && view === 'back') b.stamp(poly([[-4, sh[1]], [4, sh[1]], [6, hip[1] + 8], [-6, hip[1] + 8]], 0, hip[1] - 2, 6, 9), { name: 'cloakW' });
  b.stamp(capsule(-2, hip[1], -2.2, -1 + lL, 1.7, 1.5), { name: 'pants' });
  b.stamp(capsule(2, hip[1], 2.2, -1 + lR, 1.7, 1.5), { name: 'pants' });
  b.stamp(capsule(-2.3, hip[1] + 6, -2.3, -1 + lL, 1.6, 1.6), { name: 'boots' });
  b.stamp(capsule(2.3, hip[1] + 6, 2.3, -1 + lR, 1.6, 1.6), { name: 'boots' });
  const handL = P.arms === 'push' ? [-7.5, sh[1] - 5] : [-6.3, hip[1] + 3.5], handR = P.arms === 'push' ? [7.5, sh[1] - 5] : [6.3, hip[1] + 3.5];
  const armBack = P.arms === 'push';
  const drawArms = () => {
    b.stamp(capsule(-5, sh[1] + 1, handL[0] + .5, handL[1] + 1.5, 1.3, 1.2), { name: tunic });
    b.stamp(capsule(5, sh[1] + 1, handR[0] - .5, handR[1] + 1.5, 1.3, 1.2), { name: tunic });
    b.stamp(disc(handL[0], handL[1], 1.2), { name: ch === 'arlo' ? 'leather' : 'skin' });
    b.stamp(disc(handR[0], handR[1], 1.2), { name: ch === 'arlo' ? 'leather' : 'skin' });
  };
  if (!armBack) drawArms();
  b.stamp(poly([[-4, sh[1]], [4, sh[1]], [4.6, hip[1] + 3.5], [-4.6, hip[1] + 3.5]], 0, hip[1] - 4, 4.5, 7), { name: tunic });
  b.stamp(poly([[-4.4, hip[1] - 2], [4.4, hip[1] - 2], [4.4, hip[1]], [-4.4, hip[1]]], 0, hip[1] - 1, 5, 3), { name: 'leather' });
  if (view === 'front') { b.raw(0, hip[1] - 1, C.amber); b.raw(0, hip[1], C.brown); }
  if (D.sword && view === 'back') { b.stamp(capsule(4.5, hip[1] - 1, 7.5, hip[1] + 6, .9, .8), { name: 'leather' }); }
  if (D.sword && view === 'front') { b.stamp(capsule(-4.5, hip[1] - 1, -7.5, hip[1] + 6, .9, .8), { name: 'leather' }); b.stamp(capsule(-4, hip[1] - 1.5, -2.5, hip[1] - 4, .6), { name: 'steel' }); }
  if (ch === 'arlo') { b.stamp(disc(view === 'front' ? -4.5 : 4.5, sh[1] + 1, 2.2), { name: 'steel' }); }
  const hs = head(ch, view); b.sprite(hs, -7, sh[1] - 13 - (P.headUp || 0));
  if (ch === 'arlo') ahoge(b, 0, sh[1] - 13 - (P.headUp || 0), 0, opts.t || 0);
  if (P.headUp) { b.raw(-1, sh[1] - 1, C.skinS); b.raw(0, sh[1] - 1, C.skinS); b.raw(1, sh[1] - 1, C.skinS); }
  if (opts.scarf ?? D.scarf) b.stamp(poly([[-4, sh[1] - 2], [4, sh[1] - 2], [4, sh[1] + .5], [-4, sh[1] + .5]], 0, sh[1] - 2, 4, 2), { name: 'scarf' });
  if (armBack) drawArms();
  return b.finish();
}
// Scarf tail (side view): two chains, stepped through a three-frame cycle at 8 fps (like 3-frame hand-drawn flutter), wind 0..1, dir = 1 faces right
export function scarfTail(fb, x, y, t, wind = .5, dir = 1, len = 15, pal = [C.scarfD, C.scarf, C.scarfL]) {
  const ph = (Math.floor(t * 8) % 3) * 2.1;
  for (let k = 0; k < 2; k++) {
    const L2 = len - k * 4;
    for (let i = 1; i <= L2; i++) {
      const f = i / L2;
      const wave = Math.sin(ph - i * .62 + k * 1.4) * (0.5 + wind * 1.7) * f;
      const nx = x - dir * i * (0.3 + wind * .7), ny = y + k + i * (1 - wind * .85) * .75 + wave;
      const X = Math.round(nx), Y = Math.round(ny);
      const lit = Math.sin(ph - i * .62 + k * 1.4) > .45;
      fb.px(X, Y, i === L2 ? pal[0] : lit ? pal[2] : (k ? pal[0] : pal[1]));
      fb.px(X, Y + 1, i === L2 ? C.ink : (k ? C.ink : pal[0]));
    }
  }
}
// Scarf tail (back view): hangs from the nape and drifts to one side
export function scarfTailBack(fb, x, y, t, wind = .5, len = 13, pal = [C.scarfD, C.scarf, C.scarfL]) {
  const ph = (Math.floor(t * 8) % 3) * 2.1;
  for (let k = 0; k < 2; k++) {
    const L2 = len - k * 3, side = k ? -1 : 1;
    for (let i = 1; i <= L2; i++) {
      const f = i / L2, wave = Math.sin(ph - i * .7 + k * 2) * (0.4 + wind * 1.4) * f;
      const X = Math.round(x + side * (1 + i * .12) + (wind * i * .55) + wave), Y = Math.round(y + i * .95);
      fb.px(X, Y, i === L2 ? pal[0] : Math.sin(ph - i * .7 + k) > .5 ? pal[2] : pal[1]);
      fb.px(X + 1, Y, C.ink);
    }
  }
}

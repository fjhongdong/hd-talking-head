// Backstage: the puppeteer's hands (silhouette + warm rim light), oil lamps (lit / out + thin smoke), posts, the stage's wooden frame
import { canvas } from './carve.js';
import { vnoise, hash, mulberry } from '/core/lib.js';

const W = 1920, H = 1080;
const [mc, mg] = canvas(W, H), [rc, rg] = canvas(W, H), [oc, og] = canvas(W, H);

// —— Silhouette compositing: dark body + warm rim light on the side facing the light ——
// draw(mask) paints the shape in white on mask; dir = unit vector pointing at the light; k = rim width
export function silhouette(g, draw, { dir = [.6, -.8], k = 5, dark = '#0c0705', rim = '#ffb05a', rimA = .9, blur = 0 } = {}) {
  mg.setTransform(1, 0, 0, 1, 0, 0); mg.clearRect(0, 0, W, H); mg.fillStyle = '#fff'; mg.strokeStyle = '#fff'; mg.lineCap = 'round'; mg.lineJoin = 'round';
  draw(mg);
  og.setTransform(1, 0, 0, 1, 0, 0); og.clearRect(0, 0, W, H); og.globalCompositeOperation = 'source-over'; og.filter = 'none';
  og.drawImage(mc, 0, 0); og.globalCompositeOperation = 'source-in'; og.fillStyle = dark; og.fillRect(0, 0, W, H);
  rg.setTransform(1, 0, 0, 1, 0, 0); rg.clearRect(0, 0, W, H); rg.globalCompositeOperation = 'source-over'; rg.filter = 'none';
  rg.drawImage(mc, 0, 0); rg.globalCompositeOperation = 'destination-out'; rg.filter = 'blur(1.6px)'; rg.drawImage(mc, -dir[0] * k, -dir[1] * k);
  rg.filter = 'none'; rg.globalCompositeOperation = 'source-in'; rg.fillStyle = rim; rg.fillRect(0, 0, W, H);
  og.globalCompositeOperation = 'source-over'; og.globalAlpha = rimA; og.filter = 'blur(.7px)'; og.drawImage(rc, 0, 0); og.globalAlpha = 1; og.filter = 'none';
  g.save(); g.setTransform(1, 0, 0, 1, 0, 0); if (blur) g.filter = `blur(${blur}px)`; g.drawImage(oc, 0, 0); g.restore();
}

// —— Hand: chains of capsule-shaped finger bones + palm ——
const cap = (g, pts, w) => { for (let i = 0; i < pts.length - 1; i++) { const ww = Array.isArray(w) ? w[i] : w; g.lineWidth = ww; g.beginPath(); g.moveTo(...pts[i]); g.lineTo(...pts[i + 1]); g.stroke(); } };
const tf = (M, p) => [M[0] * p[0] + M[2] * p[1] + M[4], M[1] * p[0] + M[3] * p[1] + M[5]];
// Wide sleeve: an elliptical cuff round the wrist, widening downward, edge slightly wavy
function sleeve(g, T, k, side = 1) {
  g.beginPath(); const pts = [[-40, 30], [-58, 60], [-80, 140], [-104, 280], [110, 280], [86, 150], [66, 62], [44, 30]].map(p => T([p[0] * side, p[1]]));
  g.moveTo(...pts[0]); for (const p of pts) g.lineTo(...p); g.closePath(); g.fill();
  g.beginPath(); const c = T([2 * side, 44]); g.ellipse(c[0], c[1], 52 * k, 18 * k, Math.atan2(T([1, 0])[1] - T([0, 0])[1], T([1, 0])[0] - T([0, 0])[0]), 0, 7); g.fill();
  g.beginPath(); const w = [[-30, -12], [-34, 40], [34, 40], [30, -12]].map(T); g.moveTo(...w[0]); for (const p of w) g.lineTo(...p); g.closePath(); g.fill();   // wrist
}
// Right hand grips the main rod (back of the hand to camera, thumb on the left). M = local → viewport; local origin = wrist centre, -y = pointing direction
export function fistHand(g, M, grip = 1) {
  const k = Math.hypot(M[0], M[1]), T = p => tf(M, p);
  sleeve(g, T, k, 1);
  // Back of the hand
  g.beginPath(); const pl = [[-40, 2], [-47, -30], [-46, -66], [-38, -86], [36, -88], [44, -70], [42, -30], [34, 2]].map(T); g.moveTo(...pl[0]);
  for (let i = 1; i < pl.length; i++) g.lineTo(...pl[i]); g.closePath(); g.fill();
  // Four knuckles (fist: proximal phalanges curl forward, showing only the knuckle ridges + a little of the middle phalanges)
  const kn = [[-28, -86, 21], [-8, -91, 22], [13, -90, 21], [31, -84, 18]];
  for (const [x, y, w] of kn) { cap(g, [T([x, y + 8]), T([x - 1, y - 6 * grip]), T([x + 3, y - 14 * grip])], [w * k, w * .92 * k]); }
  // Thumb: comes out from the side of the palm and presses on the rod (under pressure: the tip joint bends back)
  cap(g, [T([-44, -24]), T([-58, -52]), T([-50, -82]), T([-33, -98])], [26 * k, 22 * k, 18 * k]);
  g.beginPath(); g.arc(...T([-31, -100]), 9 * k, 0, 7); g.fill();
  return { grip: T([-6, -104]) };
}
// Left hand pinches the two arm rods (back of the hand to camera, thumb on the right): one held between index finger and thumb, one between middle and ring fingers
export function pinchHand(g, M, sp = 0) {
  const k = Math.hypot(M[0], M[1]), T = p => tf(M, p);
  sleeve(g, T, k, -1);
  g.beginPath(); const pl = [[-34, 2], [-42, -34], [-38, -68], [-28, -84], [32, -86], [40, -66], [42, -30], [34, 2]].map(T); g.moveTo(...pl[0]); for (let i = 1; i < pl.length; i++) g.lineTo(...pl[i]); g.closePath(); g.fill();
  const s = sp;
  // Little and ring fingers: curled forward (from behind only short knuckles show)
  cap(g, [T([-28, -76]), T([-33, -94]), T([-30, -104])], [16 * k, 13 * k]);
  cap(g, [T([-12, -84]), T([-15, -106]), T([-11, -116])], [19 * k, 15 * k]);
  // Middle finger: bent slightly toward the thumb, pressed against the index finger to clamp one rod
  cap(g, [T([6, -88]), T([8, -122]), T([16 + s * 3, -142]), T([24 + s * 4, -152])], [20 * k, 17 * k, 14 * k]);
  // Index finger: further right, middle joint bent, fingertip pressing the rod
  cap(g, [T([26, -84]), T([34, -114]), T([44, -130]), T([54, -134])], [20 * k, 17 * k, 14 * k]);
  // Thumb: angles up from the lower right of the palm, tip pushing against the index finger (the pinch's pressure point), tip joint slightly bent back
  cap(g, [T([40, -18]), T([62, -46]), T([70, -80]), T([64, -106])], [26 * k, 22 * k, 18 * k]);
  g.beginPath(); g.arc(...T([63, -109]), 9.5 * k, 0, 7); g.fill();
  return { gripA: T([58, -124]), gripB: T([20, -150]) };
}
// —— Oil lamp: stand + bowl + wick + flame (lit 0..1) + smoke after it goes out ——
export function lampBody(g, x, y, s) {   // drawn in white into the mask
  const P = (a, b) => [x + a * s, y + b * s];
  g.beginPath(); g.moveTo(...P(-34, -4)); g.quadraticCurveTo(...P(-30, 14), ...P(0, 16)); g.quadraticCurveTo(...P(30, 14), ...P(34, -4)); g.lineTo(...P(24, -2)); g.lineTo(...P(-24, -2)); g.closePath(); g.fill();   // lamp bowl
  g.beginPath(); g.moveTo(...P(-5, 14)); g.lineTo(...P(5, 14)); g.lineTo(...P(6, 60)); g.lineTo(...P(-6, 60)); g.closePath(); g.fill();                                   // short stem
  g.beginPath(); g.ellipse(...P(0, 34), 10 * s, 5 * s, 0, 0, 7); g.fill();
  g.beginPath(); g.moveTo(...P(-22, 60)); g.lineTo(...P(22, 60)); g.lineTo(...P(16, 68)); g.lineTo(...P(-16, 68)); g.closePath(); g.fill();                               // base
  g.lineWidth = 2.2 * s; g.beginPath(); g.moveTo(...P(-20, 64)); g.lineTo(...P(0, -260)); g.moveTo(...P(20, 64)); g.lineTo(...P(0, -260)); g.stroke();                  // hanging cords
  g.lineWidth = 3 * s; g.beginPath(); g.moveTo(...P(12, -4)); g.lineTo(...P(20, -10)); g.stroke();                                                                         // wick
}
export function flame(g, x, y, s, t, a = 1) {   // drawn additively (lighter)
  if (a <= 0) return;
  const f = 1 + .08 * Math.sin(t * 31) + .06 * vnoise(t * 9) - .03, sw = (vnoise(t * 5 + 3) - .5) * 5 * s;
  g.save(); g.globalCompositeOperation = 'lighter'; g.globalAlpha = a;
  const gx = x + 20 * s, gy = y - 12 * s;
  let gr = g.createRadialGradient(gx, gy - 18 * s, 0, gx, gy - 18 * s, 260 * s); gr.addColorStop(0, 'rgba(255,190,110,.55)'); gr.addColorStop(.25, 'rgba(255,150,70,.18)'); gr.addColorStop(1, 'rgba(255,120,40,0)');
  g.fillStyle = gr; g.fillRect(gx - 260 * s, gy - 280 * s, 520 * s, 520 * s);
  g.beginPath(); g.moveTo(gx - 7 * s, gy); g.quadraticCurveTo(gx - 9 * s, gy - 18 * s * f, gx + sw, gy - 40 * s * f); g.quadraticCurveTo(gx + 9 * s, gy - 18 * s * f, gx + 7 * s, gy); g.closePath();
  gr = g.createLinearGradient(0, gy, 0, gy - 40 * s); gr.addColorStop(0, 'rgba(120,150,255,.8)'); gr.addColorStop(.18, 'rgba(255,240,200,1)'); gr.addColorStop(.6, 'rgba(255,190,90,.95)'); gr.addColorStop(1, 'rgba(255,120,40,.2)');
  g.fillStyle = gr; g.fill();
  g.restore();
}
// Thin smoke: a few wisps rising from the wick and drifting left and right; bright(x,y) gives how strongly a point is lit by the lamps
export function smoke(g, x, y, s, t, age, bright, seed = 1) {
  if (age <= 0) return;
  const r = mulberry(seed);
  g.save(); g.lineCap = 'round';
  for (let w = 0; w < 3; w++) {
    const ph = r() * 10, amp = 10 + r() * 16, len = Math.min(1, age / 2.5) * (300 + r() * 160) * s;
    const pts = [];
    for (let i = 0; i < 44; i++) {
      const u = i / 43, yy = y - 10 * s - u * len, xx = x + 20 * s + Math.sin(u * 5 + t * .9 + ph) * amp * u * s * (1 + u) + (vnoise(u * 3 + t * .4 + ph) - .5) * 34 * u * s;
      pts.push([xx, yy, u]);
    }
    for (let i = 1; i < pts.length; i++) {
      const [xx, yy, u] = pts[i], b = bright(xx, yy), fade = (1 - u * .85) * Math.min(1, age * .8);
      g.lineWidth = (2.5 + u * 10) * s;
      // Against the backlit cloth the smoke is a pale brown wisp; near the last remaining lamp it is lit to a warm white
      g.globalCompositeOperation = 'source-over'; g.strokeStyle = `rgba(70,48,34,${.2 * fade * (1 - b)})`;
      g.beginPath(); g.moveTo(pts[i - 1][0], pts[i - 1][1]); g.lineTo(xx, yy); g.stroke();
      g.globalCompositeOperation = 'lighter'; g.strokeStyle = `rgba(255,200,140,${.32 * fade * b})`;
      g.beginPath(); g.moveTo(pts[i - 1][0], pts[i - 1][1]); g.lineTo(xx, yy); g.stroke();
    }
  }
  g.restore();
}

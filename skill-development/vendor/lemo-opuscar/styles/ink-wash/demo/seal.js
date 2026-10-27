// Vermilion square seal in baiwen (白文, intaglio: the characters are carved away and print white) reading "水": the seal text is seal-script-like lines drawn in code (one long S-shaped stroke in the middle, two zigzag water-ripple segments on each side)
import { vnoise, clamp } from '/core/lib.js';
import { VERM } from './hero.js';
export function seal(c, x, y, size, am = 1, seed = 3) {
  if (am <= 0) return;
  c.save(); c.translate(x, y);
  const S = size, jit = S * .018;
  // Seal face: a slightly irregular square
  c.beginPath();
  const N = 28;
  for (let i = 0; i < N; i++) {
    const t = i / N * 4, side = Math.floor(t), u = t - side;
    let px, py; if (side === 0) { px = u * S; py = 0; } else if (side === 1) { px = S; py = u * S; } else if (side === 2) { px = S - u * S; py = S; } else { px = 0; py = S - u * S; }
    px += (vnoise(seed + i * 1.3) - .5) * jit * 2; py += (vnoise(seed + 40 + i * 1.3) - .5) * jit * 2;
    i ? c.lineTo(px, py) : c.moveTo(px, py);
  }
  c.closePath(); c.fillStyle = `rgba(${VERM.join(',')},${clamp(am)})`; c.fill();
  // Seal text (carved out white)
  c.globalCompositeOperation = 'destination-out';
  c.fillStyle = '#000'; c.strokeStyle = '#000'; c.lineCap = 'round'; c.lineJoin = 'round';
  c.lineWidth = S * .085;
  const P = pts => { c.beginPath(); pts.forEach(([a, b], i) => { const X = a * S + (vnoise(seed + i * 2.1 + a * 9) - .5) * jit, Y = b * S + (vnoise(seed + 7 + i * 2.1 + b * 9) - .5) * jit; i ? c.lineTo(X, Y) : c.moveTo(X, Y); }); c.stroke(); };
  P([[.5, .12], [.5, .3], [.42, .4], [.5, .5], [.58, .6], [.5, .7], [.5, .88]]);          // middle stroke
  P([[.3, .16], [.3, .3], [.2, .38], [.2, .46]]);                                          // upper left
  P([[.17, .58], [.28, .64], [.28, .8], [.34, .86]]);                                      // lower left
  P([[.7, .16], [.7, .3], [.8, .38], [.8, .46]]);                                          // upper right
  P([[.83, .58], [.72, .64], [.72, .8], [.66, .86]]);                                      // lower right
  // Uneven seal paste: tiny white specks
  for (let i = 0; i < 70; i++) { const a = vnoise(seed + i * 3.7) , b = vnoise(seed + 91 + i * 2.9); c.globalAlpha = .5 + .5 * vnoise(i * 1.1); c.beginPath(); c.arc(a * S, b * S, S * (.004 + .012 * vnoise(i * 5.3)), 0, 7); c.fill(); }
  c.restore();
}

// Subtitles (red-paper hengpi (横批, horizontal banner over a door)), paper-cut title lettering, end-card couplets
import { PAL, canvas, piece, fill, trace, finishPaper, Pl, rnd } from './paper.js';
import { rosette } from './motifs.js';
import { put } from './rig.js';

// paper-cut text piece: fill the text as red paper (yangke (阳刻, relief cut: the shape stays as paper)), add texture and cut edges
const TXT = {};
export function textPiece(s, size, wt = 800, col = PAL.red, font = 'Fraunces', seed = 3, ls = 0) {
  const key = [s, size, wt, col, font, ls].join('|'); if (TXT[key]) return TXT[key];
  const [m, mg] = canvas(10, 10); mg.font = `${wt} ${size}px "${font}"`; if (ls) mg.letterSpacing = ls + 'px';
  const w = Math.ceil(mg.measureText(s).width) + 20, h = Math.ceil(size * 1.3), K = 2;
  const [c, g] = canvas(w * K, h * K); g.scale(K, K); g.font = `${wt} ${size}px "${font}"`; if (ls) g.letterSpacing = ls + 'px';
  g.fillStyle = col; g.textBaseline = 'alphabetic'; g.fillText(s, 10, size * 1.02);
  finishPaper(c, g, { seed, edge: 1.4 });
  return TXT[key] = { c, x0: 0, y0: 0, w, h, K };
}
// subtitle strip: dark-red paper banner, swallowtail sawtooth at both ends, scattered gold flecks
const SUBS = {};
function subStrip(text) {
  if (SUBS[text]) return SUBS[text];
  const [m, mg] = canvas(10, 10); mg.font = '600 44px "Fraunces"';
  const tw = mg.measureText(text).width, w = Math.ceil(tw + 150), h = 74, K = 1.5;
  const [c, g] = canvas(w * K, h * K); g.scale(K, K);
  const pts = [[0, 4], [w, 4], [w - 22, h / 2], [w, h - 4], [0, h - 4], [22, h / 2]];
  // top and bottom sawtooth edges
  const poly = []; for (let x = 0; x <= w; x += 10) poly.push([x, 4 + (x / 10 % 2) * 3]);
  poly.push([w - 22, h / 2]); for (let x = w; x >= 0; x -= 10) poly.push([x, h - 4 - (x / 10 % 2) * 3]); poly.push([22, h / 2]);
  g.beginPath(); trace(g, Pl(poly, true, .3, 5)); g.fillStyle = PAL.sub; g.fill();
  // gold flecks
  for (let k = 0; k < 40; k++) { g.fillStyle = `rgba(222,178,84,${.25 + rnd(k, 3) * .35})`; g.beginPath(); g.arc(30 + rnd(k, 1) * (w - 60), 10 + rnd(k, 2) * (h - 20), .8 + rnd(k, 4) * 1.4, 0, 7); g.fill(); }
  rosette(g, 50, h / 2, 13, 6, 0, .25);
  finishPaper(c, g, { seed: 9, edge: 1 });
  g.setTransform(K, 0, 0, K, 0, 0); g.font = '600 44px "Fraunces"'; g.fillStyle = '#fff1d6'; g.textBaseline = 'middle'; g.textAlign = 'left';
  g.fillText(text, 80, h / 2 + 2);
  return SUBS[text] = { c, w, h };
}
// subtitles: cues = [{t0,t1,text}]; drop in from above like pasting up spring couplets (12 fps, two steps)
export function drawSubs(g, t, cues) {
  for (const q of cues) {
    if (t < q.t0 || t > q.t1) continue;
    const s = subStrip(q.text), u = Math.floor((t - q.t0) * 12) / 12, drop = u < .08 ? -14 : u < .16 ? -5 : 0, a = Math.min(1, (q.t1 - t) / .2);
    const x = 960 - s.w / 2, y = 1080 - 70 - s.h + drop;
    g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = Math.max(0, a);
    g.shadowColor = 'rgba(30,4,8,.45)'; g.shadowBlur = 8; g.shadowOffsetX = 3; g.shadowOffsetY = 5;
    g.drawImage(s.c, x, y, s.w, s.h); g.restore();
  }
}

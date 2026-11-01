// Subtitles = tiba (题跋, inscriptions): small italic characters in jiao (焦墨, scorched/darkest ink), placed in the picture's liubai (留白, left-blank space), with a small vermilion seal at the start of each line; they appear/dissolve as ink blooms
import { clamp } from '/core/lib.js';
import { VERM } from './hero.js';
export function subtitle(A, text, x, y, a = 1, o = {}) {
  if (a <= 0) return;
  const size = o.size || 46, lines = text.split('\n');
  const c = A.cd, w = A.cw;
  // On appearing they are "wet" first (into the wet layer, bleeding), then "dry" (dry layer, sharp)
  const wetK = o.wetK ?? clamp(1 - a) * .8;
  for (const [ctx, k] of [[w, wetK], [c, 1 - wetK * .6]]) {
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = clamp(a * k * .9); ctx.fillStyle = '#000';
    ctx.font = `italic 500 ${size}px Cormorant`; ctx.letterSpacing = '1px'; ctx.textBaseline = 'alphabetic';
    lines.forEach((ln, i) => ctx.fillText(ln, x + size * .62, y + i * size * 1.22));
    ctx.restore();
  }
  // Small seal at the start of the line
  const s = size * .32, cc = A.cc;
  cc.save(); cc.setTransform(1, 0, 0, 1, 0, 0); cc.globalAlpha = clamp(a * .92); cc.fillStyle = `rgb(${VERM.join(',')})`;
  cc.fillRect(x, y - size * .36 - s / 2, s, s); cc.restore();
}

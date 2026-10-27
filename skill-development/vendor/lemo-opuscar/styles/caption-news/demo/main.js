// Caption News (字幕新闻) ·《蜜蜂账本 The Bee Ledger》— 1920×1080, 30 fps, 59.5 s
// One timeline (SHOTS, CAPS, VO, EV) drives the picture, the captions, the .srt and the mix.
// Footage frames are prepared at their final size by tools/prep.sh; the page only pans/pushes within the allowed scale.
const W = 1920, H = 1080, FPS = 30, DUR = 59.5;
const cv = document.getElementById('out'), ctx = cv.getContext('2d');

// ---------- helpers ----------
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const eo = t => 1 - Math.pow(1 - clamp(t), 3);
const ei = t => Math.pow(clamp(t), 3);
const eio = t => { t = clamp(t); return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
const back = (t, s = 1.8) => { t = clamp(t) - 1; return 1 + t * t * ((s + 1) * t + s); };
const fmt = n => Math.round(n).toLocaleString('en-US');

// ---------- palette, type, layout ----------
const C = { bg: '#0E0E0C', panel: '#151512', ink: '#F7F5EF', honey: '#FFC21A', loss: '#FF4A3D', grey: '#8D8B83', rule: 'rgba(255,255,255,.045)', margin: 'rgba(255,74,61,.38)', dim: 'rgba(247,245,239,.74)' };
const F = { zh9: "'SC9'", zh5: "'SC5'", n8: "'IT8','SC9'", n5: "'IT5','SC5'", it: "'IT6I','IT5'" };
const CAP = { x: 120, zhY: 948, zh: 88, enY: 1014, en: 33 };       // caption card: one Chinese line + one English line, left aligned
const GRADE = 'contrast(1.07) saturate(0.92) brightness(0.98)';     // one grade for every piece of footage

// ---------- timeline (every cut on the 120 BPM half-beat grid) ----------
const SHOTS = [
  { a: 0.0, b: 1.5, k: 'vid', fr: 'h1', n: 48, z: [1.0, 1.035], cr: '视频 Altena TV · CC BY 3.0' },
  { a: 1.5, b: 3.0, k: 'vid', fr: 'h2', n: 49, z: [1.0, 1.0], cr: '视频 USDA · 公有领域' },
  { a: 3.0, b: 5.0, k: 'vid', fr: 'h3', n: 64, z: [1.0, 1.05], cr: '视频 Phonon.b · CC BY 4.0' },
  { a: 5.0, b: 7.5, k: 'sting', cr: '视频 Midsummer Bees · CC BY 3.0' },
  { a: 7.5, b: 10.5, k: 'half', cr: '视频 Altena TV · CC BY 3.0' },
  { a: 10.5, b: 13.0, k: 'freeze', cr: '视频 Martin J. Calabrese · CC BY 3.0' },
  { a: 13.0, b: 16.0, k: 'doc6' },
  { a: 16.0, b: 19.0, k: 'stock' },
  { a: 19.0, b: 23.5, k: 'split', cr: '视频 Altena TV · CC BY 3.0 ｜ USDA · 公有领域' },
  { a: 23.5, b: 27.5, k: 'grid', cr: '视频 USDA ｜ 照片 vastateparksstaff · CC BY 2.0 ｜ USGS' },
  { a: 27.5, b: 30.0, k: 'quote' },
  { a: 30.0, b: 33.0, k: 'sem', cr: '电镜照片 USDA ARS · 公有领域' },
  { a: 33.0, b: 37.5, k: 'stress' },
  { a: 37.5, b: 41.5, k: 'loss' },
  { a: 41.5, b: 45.5, k: 'map' },
  { a: 45.5, b: 46.5, k: 'almond', cr: '照片 USDA · 加州杏仁园 2014 · 公有领域' },
  { a: 46.5, b: 50.0, k: 'vid', fr: 'rb', n: 109, z: [1.0, 1.03], cr: '视频 USDA · 公有领域', lt: ['USDA 屋顶蜂场 · 华盛顿', 'USDA rooftop apiary, Washington, D.C. · 2013'] },
  { a: 50.0, b: 54.5, k: 'vid', fr: 'vd', n: 123, z: [1.0, 1.06], cr: '视频 Martin J. Calabrese · CC BY 3.0' },
  { a: 54.5, b: 59.5, k: 'end' },
];
// captions, voice starts and music marks live in timeline.json (shared with audio/mix.py and the .srt)
let TL = null, CAPS = [], HOOK_CUE = [], VO = {};
const shotAt = t => SHOTS.find(s => t >= s.a && t < s.b) || SHOTS[SHOTS.length - 1];

// ---------- loading ----------
// Drawing is synchronous: render(t) draws once with whatever is loaded (placeholders for the rest, so TEXTS(t) is valid
// at once, as readcheck needs), then loads what was missing and draws again.
const DIMS = { sem: [2400, 1710], almond: [2548, 1700], package: [1368, 1824], queen: [1920, 1280], doc1: [1870, 2420], st: [1056, 1080], sl: [960, 1080], sr: [960, 1080], g1: [648, 1080] };
const LOADED = new Map(), NEED = new Set(), PH = new Map();
function placeholder(src) {
  if (!PH.has(src)) { const key = (src.match(/(?:fr\/([a-z0-9]+)_|img\/([a-z0-9]+)\.)/) || []).slice(1).find(Boolean); const [w, h] = DIMS[key] || [1920, 1080]; PH.set(src, { width: w, height: h, ph: true }); }
  return PH.get(src);
}
function getImg(src) { const im = LOADED.get(src); if (im) return im; NEED.add(src); return placeholder(src); }
function load(src) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => im.decode().then(() => res(im), () => res(im)); im.onerror = () => rej(new Error('missing ' + src)); im.src = src; })
    .then(im => { LOADED.set(src, im); if (src.startsWith('assets/fr') && LOADED.size > 90) { for (const k of LOADED.keys()) if (k.startsWith('assets/fr')) { LOADED.delete(k); break; } } });
}
const img = src => getImg(src);
const frame = (fr, n, t, a) => getImg(`assets/fr/${fr}_${String(clamp(Math.floor((t - a) * FPS + 1e-6) + 1, 1, n)).padStart(3, '0')}.jpg`);
function di(im, ...a) { if (!im.ph) ctx.drawImage(im, ...a); }
let STATES = null;

// ---------- drawing basics ----------
function text(s, x, y, font, color, align = 'left', base = 'alphabetic') { ctx.font = font; ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = base; ctx.fillText(s, x, y); }
function tw(s, font) { ctx.font = font; return ctx.measureText(s).width; }
function warm(x, y, w, h, a = 0.06) { ctx.save(); ctx.globalCompositeOperation = 'soft-light'; ctx.fillStyle = `rgba(255,170,70,${a})`; ctx.fillRect(x, y, w, h); ctx.restore(); }
// draw a prepared frame (already at display size) into a box, with a push (z ≥ 1) around (fx, fy) in box fractions
function plate(im, x, y, w, h, z = 1, fx = .5, fy = .5, filt = GRADE) {
  ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  const ox = x + (w - im.width) / 2, oy = y + (h - im.height) / 2, px = x + w * fx, py = y + h * fy;
  ctx.filter = filt; di(im, px + (ox - px) * z, py + (oy - py) * z, im.width * z, im.height * z); ctx.filter = 'none';
  warm(x, y, w, h); ctx.restore();
}
// draw a photo by cover-fit at scale s (photo px → screen px), centred on photo point (px, py) placed at screen (sx, sy)
function photo(im, s, px, py, sx = W / 2, sy = H / 2, filt = GRADE, box = [0, 0, W, H]) {
  ctx.save(); ctx.beginPath(); ctx.rect(...box); ctx.clip();
  const dw = im.width * s, dh = im.height * s;
  const dx = clamp(sx - px * s, box[0] + box[2] - dw, box[0]), dy = clamp(sy - py * s, box[1] + box[3] - dh, box[1]);
  ctx.filter = filt; di(im, dx, dy, dw, dh); ctx.filter = 'none';
  warm(...box); ctx.restore(); return { dx, dy, s };
}
function veil(kind = 'v') { if (kind === 'c') shade(820, .6); else { shade(); topShade(); } }
function shade(top = 560, a = .84) {   // bottom gradient under the caption card
  const g = ctx.createLinearGradient(0, top, 0, H); g.addColorStop(0, 'rgba(14,14,12,0)'); g.addColorStop(.55, `rgba(14,14,12,${a * .7})`); g.addColorStop(1, `rgba(14,14,12,${a})`);
  ctx.fillStyle = g; ctx.fillRect(0, top, W, H - top);
  const r = ctx.createRadialGradient(0, H, 0, 0, H, 1100); r.addColorStop(0, 'rgba(14,14,12,.45)'); r.addColorStop(1, 'rgba(14,14,12,0)'); ctx.fillStyle = r; ctx.fillRect(0, 0, W, H);
}
function topShade() { const g = ctx.createLinearGradient(0, 0, 0, 200); g.addColorStop(0, 'rgba(14,14,12,.55)'); g.addColorStop(1, 'rgba(14,14,12,0)'); ctx.fillStyle = g; ctx.fillRect(0, 0, W, 200); }
function flash(t, t0, dur = 0.12) { const k = seg(t, t0, t0 + dur); if (k <= 0 || k >= 1) return; ctx.fillStyle = `rgba(255,255,255,${(1 - k) * .9})`; ctx.fillRect(0, 0, W, H); }
// ledger paper: the data-card ground (dark ruled sheet with a red double margin) — the film's graphic motif
function ledger(t, a, slide = true) {
  const k = slide ? eo(seg(t, a, a + .18)) : 1, ox = (1 - k) * 140;
  ctx.fillStyle = C.panel; ctx.fillRect(0, 0, W, H);
  ctx.save(); ctx.translate(ox, 0);
  ctx.strokeStyle = C.rule; ctx.lineWidth = 2;
  for (let y = 120; y < H; y += 54) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  ctx.strokeStyle = C.margin; ctx.lineWidth = 2; [78, 86].forEach(x => { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); });
  ctx.restore();
  if (slide && k < 1) { ctx.fillStyle = `rgba(255,194,26,${(1 - k) * .5})`; for (let i = 0; i < 6; i++) ctx.fillRect(W - (1 - k) * 900 - i * 120, 140 + i * 150, 600 * (1 - k), 3); }
  return ox;
}
// a camera for graphics: slow push around the frame centre
function camPush(t, a, b, z0 = 1, z1 = 1.03, cx = W / 2, cy = H / 2) { const z = lerp(z0, z1, eio(seg(t, a, b))); ctx.translate(cx, cy); ctx.scale(z, z); ctx.translate(-cx, -cy); }
// numbers with fixed-width digits, so a rolling counter never jitters
function num(s, x, y, size, color, align = 'left', font = F.n8) {
  const f = `800 ${size}px ${font}`; ctx.font = f; const cw = ctx.measureText('0').width;
  const wOf = ch => /[0-9]/.test(ch) ? cw : ctx.measureText(ch).width;
  let total = 0; for (const ch of s) total += wOf(ch);
  let cx = align === 'right' ? x - total : align === 'center' ? x - total / 2 : x;
  ctx.fillStyle = color; ctx.textBaseline = 'alphabetic';
  for (const ch of s) { const w = wOf(ch); ctx.textAlign = 'center'; ctx.fillText(ch, cx + w / 2, y); cx += w; }
  return total;
}
function bug(t) {   // channel bug (fictional channel 简闻) + topic, from the end of the title sting
  const k = eo(seg(t, 7.15, 7.4)); if (k <= 0) return;
  ctx.save(); ctx.globalAlpha = k; const x = 96, y = 52;
  ctx.fillStyle = C.honey; ctx.fillRect(x, y, 92, 46); text('简闻', x + 46, y + 34, `900 30px ${F.zh9}`, C.bg, 'center');
  ctx.fillStyle = 'rgba(14,14,12,.62)'; ctx.fillRect(x + 92, y, 300, 46);
  text('蜜蜂账本', x + 108, y + 33, `900 26px ${F.zh9}`, C.ink); text('THE BEE LEDGER', x + 226, y + 31, `800 17px ${F.n8}`, C.honey);
  ctx.restore();
  TX.push({ id: 'title', text: '蜜蜂账本', x0: x, y0: y, x1: x + 392, y1: y + 46 });
  TX.push({ id: 'title-en', text: 'THE BEE LEDGER', x0: x, y0: y, x1: x + 392, y1: y + 46 });
}
function sourceTag(t, t0, label = 'USDA NASS · 2026.08.03') {   // source tag: slides in from the left under the bug
  const k = eo(seg(t, t0, t0 + .2)); if (k <= 0) return; ctx.save(); ctx.globalAlpha = k; const x = 96 - (1 - k) * 40, y = 108;
  const w1 = tw('来源', `900 22px ${F.zh9}`) + 20, w2 = tw(label, `500 21px ${F.n5}`) + 22;
  ctx.fillStyle = C.ink; ctx.fillRect(x, y, w1, 36); text('来源', x + 10, y + 26, `900 22px ${F.zh9}`, C.bg);
  ctx.fillStyle = 'rgba(14,14,12,.82)'; ctx.fillRect(x + w1, y, w2, 36); text(label, x + w1 + 11, y + 25, `500 21px ${F.n5}`, C.ink); ctx.restore();
}
function credit(s) {   // per-shot footage credit, top right ("Video:" tag); CC BY attribution on every shot it applies to
  if (!s) return; const f = `500 19px ${F.zh5}`; const w = tw(s, f);
  ctx.fillStyle = 'rgba(14,14,12,.5)'; ctx.fillRect(W - 72 - w - 16, 54, w + 16, 30); text(s, W - 80, 75, f, 'rgba(247,245,239,.86)', 'right');
}
function lowerThird(t, t0, zh, en, x = 120, y = 742) {   // lower third: yellow bar + label + one English line
  const k = eo(seg(t, t0, t0 + .22)); if (k <= 0) return;
  const w = Math.max(tw(zh, `900 40px ${F.zh9}`), tw(en, `500 22px ${F.n5}`)) + 48;
  ctx.save(); ctx.beginPath(); ctx.rect(x, y - 4, w * k + 10, 110); ctx.clip();
  ctx.fillStyle = C.honey; ctx.fillRect(x, y, 8, 96); ctx.fillStyle = 'rgba(14,14,12,.78)'; ctx.fillRect(x + 8, y, w, 96);
  text(zh, x + 30, y + 48, `900 40px ${F.zh9}`, C.ink); text(en, x + 30, y + 82, `500 22px ${F.n5}`, C.dim); ctx.restore();
  TX.push({ id: 'lt' + t0, text: zh, x0: x, y0: y, x1: x + w + 8, y1: y + 96 });
}

// ---------- caption card: one line per language, chunks slam in one after another ----------
function capCard(c, t) {
  const [a, b, zh, en, big = 1] = c; if (t < a || t >= b) return;
  const size = CAP.zh * big, parts = zh.split('|'); let cx = CAP.x; const y = CAP.zhY - (big > 1 ? 40 : 0);
  parts.forEach((p, i) => {
    const t0 = a + .04 + i * .12, k = seg(t, t0, t0 + .13); if (t < t0) { cx += chunkW(p, size) + size * .05; return; }
    const sc = lerp(1.3, 1, back(k, 1.6));
    ctx.save(); ctx.translate(cx, y); ctx.scale(sc, sc); ctx.globalAlpha = clamp(k * 3);
    let x = 0;
    for (const q of p.split(/(\{[^}]+\})/).filter(Boolean)) {
      const hot = q[0] === '{', s = hot ? q.slice(1, -1) : q, f = `900 ${size}px ${F.zh9}`, w = tw(s, f);
      if (hot) { const wk = eo(seg(t, t0 + .05, t0 + .17)); ctx.fillStyle = C.honey; ctx.fillRect(x - 12, -size * .9, (w + 24) * wk, size * 1.1); }
      else { ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 20; ctx.shadowOffsetY = 4; }
      text(s, x, 0, f, hot ? C.bg : C.ink); ctx.shadowColor = 'transparent'; x += w + (hot ? 24 : 0);
    }
    ctx.restore(); cx += chunkW(p, size) + size * .05;
  });
  const ke = eo(seg(t, a + .1, a + .28));
  ctx.save(); ctx.globalAlpha = ke; ctx.shadowColor = 'rgba(0,0,0,.7)'; ctx.shadowBlur = 12;
  text(en, CAP.x, CAP.enY + (big > 1 ? 4 : 0) + (1 - ke) * 10, `500 ${CAP.en}px ${F.n5}`, C.ink); ctx.restore();
}
function chunkW(p, size) { let w = 0; for (const q of p.split(/(\{[^}]+\})/).filter(Boolean)) { const hot = q[0] === '{'; w += tw(hot ? q.slice(1, -1) : q, `900 ${size}px ${F.zh9}`) + (hot ? 24 : 0); } return w; }

// ---------- shots ----------
function shotVid(s, t) {
  const im = frame(s.fr, s.n, t, s.a); const z = lerp(s.z[0], s.z[1], eio(seg(t, s.a, s.b)));
  plate(im, 0, 0, W, H, z, .5, .5); veil();
  if (s.lt) lowerThird(t, s.a + .1, ...s.lt);
}
// 0–5 s: the hook — the film's biggest number lands on frame 4 and rolls
function hook(t) {
  if (t < .06 || t >= 4.9) return;
  const out = eo(seg(t, 4.62, 4.9));
  ctx.save(); ctx.translate(-out * 1200, 0);
  const L = 120, kk = seg(t, .06, .19);
  ctx.save(); ctx.translate(L, 470); const s1 = lerp(1.3, 1, back(kk, 1.6)); ctx.scale(s1, s1); ctx.globalAlpha = clamp(kk * 3);
  ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 22; text('一年没了', 0, 0, `900 92px ${F.zh9}`, C.ink); ctx.restore();
  const k = seg(t, .13, .26), roll = Math.round(130 * eo(seg(t, .13, .6)));
  if (t >= .13) {
    ctx.save(); ctx.translate(L, 760); const sc = lerp(1.45, 1, back(k, 1.4)); ctx.scale(sc, sc); ctx.globalAlpha = clamp(k * 3);
    const nf = 270, cw = tw('0', `800 ${nf}px ${F.n8}`), wn = cw * 3, wu = tw('万箱', `900 130px ${F.zh9}`);
    ctx.fillStyle = C.honey; ctx.fillRect(-22, -238, wn + wu + 70, 296);
    num(String(roll).padStart(3, ' ').trim(), wn, 0, nf, C.bg, 'right'); text('万箱', wn + 22, -14, `900 130px ${F.zh9}`, C.bg);
    ctx.restore();
    const kb = seg(t, .4, .53);
    if (t > .4) { ctx.save(); ctx.translate(L + 3 * cwOf(270) + tw('万箱', `900 130px ${F.zh9}`) + 120, 760); ctx.scale(lerp(1.3, 1, back(kb, 1.6)), lerp(1.3, 1, back(kb, 1.6))); ctx.globalAlpha = clamp(kb * 3); ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 22; text('蜜蜂', 0, -14, `900 130px ${F.zh9}`, C.ink); ctx.restore(); }
  }
  const ke = eo(seg(t, .3, .5)); ctx.save(); ctx.globalAlpha = ke; ctx.shadowColor = 'rgba(0,0,0,.7)'; ctx.shadowBlur = 12;
  text(HOOK_CUE[3], L, 880, `500 ${CAP.en}px ${F.n5}`, C.ink); ctx.restore();
  ctx.restore();
  if (out === 0) { TX.push({ id: 'hook', text: '一年没了130万箱蜜蜂', x0: L - 30, y0: 380, x1: 1400, y1: 820 }); }
}
const cwOf = size => tw('0', `800 ${size}px ${F.n8}`);
// 5–7.5 s: title sting — a yellow ledger page wipes in over the hive entrance, then wipes off into the bug
function shotSting(s, t) {
  const off = eio(seg(t, 7.18, 7.5));
  if (off > 0) shotHalf(SHOTS[4], 7.5);           // what the wipe-off reveals is the next shot's first frame
  else { ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H); }
  const im = frame('st', 81, t, s.a);
  const PW = 864, kin = eo(seg(t, 4.94, 5.14));
  ctx.save(); ctx.translate(-off * 1920, 0);
  plate(im, PW, 0, W - PW, H, lerp(1.0, 1.0, 0), .5, .5);
  // the page
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, PW * kin, H); ctx.clip();
  ctx.fillStyle = C.honey; ctx.fillRect(0, 0, PW, H);
  ctx.strokeStyle = 'rgba(14,14,12,.13)'; ctx.lineWidth = 2;
  for (let i = 0; i < 18; i++) { const y = 120 + i * 54, kl = eo(seg(t, 5.1 + i * .025, 5.4 + i * .025)); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(PW * kl, y); ctx.stroke(); }
  ctx.strokeStyle = 'rgba(200,40,30,.5)'; [78, 86].forEach(x => { const kl = eo(seg(t, 5.15, 5.55)); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H * kl); ctx.stroke(); });
  const kt = seg(t, 5.18, 5.32);
  if (t > 5.18) { ctx.save(); ctx.translate(124, 560); const sc = lerp(1.35, 1, back(kt, 1.5)); ctx.scale(sc, sc); ctx.globalAlpha = clamp(kt * 3); text('蜜蜂账本', 0, 0, `900 176px ${F.zh9}`, C.bg); ctx.restore(); }
  const k2 = eo(seg(t, 5.36, 5.56)); ctx.save(); ctx.globalAlpha = k2; text('THE BEE LEDGER', 128 + (1 - k2) * 30, 646, `800 58px ${F.n8}`, C.bg); ctx.restore();
  const k3 = eo(seg(t, 5.5, 5.7)); if (k3 > 0) {
    ctx.save(); ctx.globalAlpha = k3; const lab = 'USDA NASS  ·  2026.08.03', wl = tw(lab, `800 28px ${F.n8}`);
    ctx.fillStyle = C.bg; ctx.fillRect(128, 700, wl + 70, 52); ctx.fillStyle = C.loss; ctx.beginPath(); ctx.arc(152, 726, 8, 0, 7); ctx.fill();
    text(lab, 172, 737, `800 28px ${F.n8}`, C.honey); ctx.restore();
  }
  ctx.restore(); ctx.restore();
  if (t > 5.18 && off === 0) { TX.push({ id: 'title', text: '蜜蜂账本', x0: 120, y0: 400, x1: 840, y1: 600 }); TX.push({ id: 'title-en', text: 'THE BEE LEDGER', x0: 120, y0: 590, x1: 840, y1: 660 }); }
}
// 7.5–10.5 s: "half" — a yellow line sweeps to 49.5 % of the row; what it passes goes dark
function shotHalf(s, t) {
  const im = frame('hf', 94, t, s.a); const z = lerp(1.0, 1.035, eio(seg(t, s.a, s.b)));
  plate(im, 0, 0, W, H, z, .5, .5); if (t < 7.92) veil();
  const tw0 = 7.92, k = eo(seg(t, tw0, tw0 + .42));
  if (k > 0) {
    const xs = lerp(W, W * (1 - .495), k);
    ctx.save(); ctx.beginPath(); ctx.rect(xs, 0, W - xs, H); ctx.clip(); plate(im, 0, 0, W, H, z, .5, .5, 'grayscale(1) brightness(0.26) contrast(1.1)'); ctx.restore();
    veil(); ctx.fillStyle = C.honey; ctx.fillRect(xs - 4, 0, 8, H);
    const k2 = seg(t, tw0 + .36, tw0 + .5);
    if (t > tw0 + .36) {
      ctx.save(); ctx.translate(1440, 470); const sc = lerp(1.3, 1, back(k2, 1.6)); ctx.scale(sc, sc); ctx.globalAlpha = clamp(k2 * 3);
      num('≈49%', 0, 0, 200, C.ink, 'center'); ctx.restore();
      TX.push({ id: 'half', text: '≈49%', x0: 1180, y0: 300, x1: 1700, y1: 500 });
    }
  }
}
// 10.5–13 s: freeze frame — the bee is stopped mid-shot, white flash, punch in, brackets and a timecode
function shotFreeze(s, t) {
  const tf = 11.0, im = frame('fz', 42, Math.min(t, tf), s.a);
  const kp = eo(seg(t, tf, tf + .25)), z = t < tf ? 1 : lerp(1, 1.12, kp) + .04 * seg(t, tf + .25, s.b);
  const sat = t < tf ? 1 : lerp(1, .45, kp);
  plate(im, 0, 0, W, H, z, 890 / W, 490 / H, `${GRADE} saturate(${sat})`); veil();
  if (t >= tf) {
    const kb = eo(seg(t, tf + .1, tf + .3)), cx = 890, cy = 490, bw = lerp(420, 300, kb), bh = lerp(330, 230, kb), L = 46;
    ctx.save(); ctx.globalAlpha = kb; ctx.strokeStyle = C.honey; ctx.lineWidth = 6;
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) { const x = cx + sx * bw / 2, y = cy + sy * bh / 2; ctx.beginPath(); ctx.moveTo(x, y - sy * -L * 0 + (sy < 0 ? L : -L)); ctx.lineTo(x, y); ctx.lineTo(x - sx * L, y); ctx.stroke(); }
    ctx.restore();
    // timecode stamp, top right under the credit
    ctx.save(); ctx.globalAlpha = kb; ctx.fillStyle = 'rgba(14,14,12,.7)'; ctx.fillRect(W - 300, 100, 220, 44);
    ctx.fillStyle = C.loss; ctx.fillRect(W - 284, 112, 8, 20); ctx.fillRect(W - 270, 112, 8, 20);
    num('00:11:00', W - 96, 132, 26, C.ink, 'right'); ctx.restore();
  }
  flash(t, tf, .14);
}
// report page: white paper on a dark desk, 220 dpi (1 pt = 3.0556 px); highlighter marks driven by pdftotext -bbox coordinates
const PT = 220 / 72;
function paper(t, s, z0, z1, fx, fy, rot, marks) {
  const im = img('assets/img/doc1.jpg'); const u = eio(seg(t, s.a, s.b)), z = lerp(z0, z1, u);
  ctx.fillStyle = '#23221E'; ctx.fillRect(0, 0, W, H);
  ctx.save(); ctx.translate(W * .56, H * .40); ctx.rotate(rot); ctx.scale(z, z); ctx.translate(-fx * PT, -fy * PT);
  ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 50 / z; ctx.shadowOffsetY = 18 / z;
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, im.width, im.height); ctx.shadowColor = 'transparent';
  ctx.filter = 'contrast(1.06) sepia(0.06)'; di(im, 0, 0); ctx.filter = 'none';
  for (const m of marks) {   // [start, x0, y0, x1, y1] in pt
    const k = eo(seg(t, m[0], m[0] + (m[5] || .3))); if (k <= 0) continue;
    ctx.globalCompositeOperation = 'multiply'; ctx.fillStyle = 'rgba(255,200,30,.88)';
    ctx.fillRect(m[1] * PT - 8, m[2] * PT - 5, (m[3] - m[1]) * PT * k + 16, (m[4] - m[2]) * PT + 10); ctx.globalCompositeOperation = 'source-over';
  }
  ctx.restore(); warm(0, 0, W, H, .04);
  const v = ctx.createRadialGradient(W * .56, H * .4, 300, W * .56, H * .4, 1200); v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.55)'); ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
}
// 13–16 s: the turn, said by the report itself — headline highlighted, +6% lands
function shotDoc6(s, t) {
  paper(t, s, .92, 1.0, 150, 173, -.012, [[13.28, 36, 167.1, 265.4, 179.5, .45]]); veil();
  const tp = 14.25, k = seg(t, tp, tp + .14);
  if (t > tp) {
    ctx.save(); ctx.translate(1430, 640); ctx.rotate(-.03); const sc = lerp(1.4, 1, back(k, 1.5)); ctx.scale(sc, sc); ctx.globalAlpha = clamp(k * 3);
    ctx.fillStyle = C.honey; ctx.fillRect(-190, -120, 380, 160); num('+6%', 0, 10, 140, C.bg, 'center'); ctx.restore();
    TX.push({ id: 'plus6', text: '+6%', x0: 1230, y0: 500, x1: 1630, y1: 700 });
  }
  if (t > 13.0) sourceTag(t, 13.15);
  flash(t, 13.0, .1);
}
// 16–19 s: colonies on the first day of each quarter — the count rises in spring, falls in winter, ends above where it began
const STOCK = [[2.6393, '1月', '264'], [2.88, '4月', '288'], [3.12, '7月', '312'], [2.95, '10月', '295'], [2.8054, '1月', '281'], [2.84, '4月', '284']];
function shotStock(s, t) {
  ledger(t, s.a); ctx.save(); camPush(t, s.a, s.b, 1, 1.03, 1200, 480);
  const x0 = 640, x1 = 1720, yb = 760, yt = 250, X = i => lerp(x0, x1, i / 5), Y = v => lerp(yb, yt, (v - 2.4) / .8);
  text('蜂群存栏', 120, 250, `900 64px ${F.zh9}`, C.ink); text('Colonies on the 1st of each quarter, U.S.', 122, 300, `500 24px ${F.n5}`, C.grey);
  text('单位：万箱', 122, 344, `500 24px ${F.zh5}`, C.grey);
  ctx.strokeStyle = 'rgba(255,255,255,.1)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x0 - 40, yb); ctx.lineTo(x1 + 40, yb); ctx.stroke();
  STOCK.forEach(([v, m], i) => text(m, X(i), yb + 46, `500 26px ${F.zh5}`, i === 0 || i === 4 ? C.honey : C.grey, 'center'));
  text('2025', X(1.5), yb + 92, `800 26px ${F.n8}`, C.grey, 'center'); text('2026', X(4.5), yb + 92, `800 26px ${F.n8}`, C.grey, 'center');
  const kd = eio(seg(t, s.a + .2, s.a + 1.2)) * 5;
  ctx.lineWidth = 7; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.strokeStyle = C.ink;
  ctx.beginPath(); ctx.moveTo(X(0), Y(STOCK[0][0]));
  for (let i = 0; i < 5; i++) { const f = clamp(kd - i); if (f <= 0) break; ctx.lineTo(lerp(X(i), X(i + 1), f), lerp(Y(STOCK[i][0]), Y(STOCK[i + 1][0]), f)); }
  ctx.stroke();
  STOCK.forEach(([v, , lab], i) => {
    if (kd < i - .02) return; const hot = i === 0 || i === 4;
    ctx.fillStyle = hot ? C.honey : C.ink; ctx.beginPath(); ctx.arc(X(i), Y(v), hot ? 13 : 9, 0, 7); ctx.fill();
    num(lab, X(i), Y(v) - 30, 36, hot ? C.honey : C.ink, 'center');
  });
  const kb = eo(seg(t, s.a + .85, s.a + 1.1));
  if (kb > 0) {   // bracket Jan → Jan, +6 %
    const ya = Y(2.6393) + 60, xa = X(0), xb = X(4);
    ctx.strokeStyle = C.honey; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(xa, ya - 14); ctx.lineTo(xa, ya); ctx.lineTo(lerp(xa, xb, kb), ya); if (kb > .98) ctx.lineTo(xb, ya - 14); ctx.stroke();
    const k2 = seg(t, s.a + 1.05, s.a + 1.2); if (t > s.a + 1.05) { ctx.save(); ctx.translate((xa + xb) / 2, ya + 6); ctx.scale(lerp(1.3, 1, back(k2)), lerp(1.3, 1, back(k2))); ctx.fillStyle = C.honey; ctx.fillRect(-82, -2, 164, 64); num('+6%', 0, 50, 52, C.bg, 'center'); ctx.restore(); }
  }
  ctx.restore();
  veil('c'); sourceTag(t, s.a + .3);
  TX.push({ id: 'stockT', text: '蜂群存栏', x0: 110, y0: 180, x1: 400, y1: 270 });
  if (t > s.a + 1.05) TX.push({ id: 'stock6', text: '+6%', x0: 1000, y0: 620, x1: 1300, y1: 760 });
}
// 19–23.5 s: the ledger, split screen — the dead column and the rebuilt column, side by side
function shotSplit(s, t) {
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  const ko = eo(seg(t, s.a - .14, s.a + .2)), hw = 958 * ko;
  const L = frame('sl', 138, t, s.a), R = frame('sr', 139, t, s.a);
  plate(L, 960 - hw, 0, hw, H, 1.0, .5, .5, 'grayscale(.92) brightness(.5) contrast(1.15)');
  ctx.fillStyle = 'rgba(255,74,61,.12)'; ctx.fillRect(960 - hw, 0, hw, H);
  plate(R, 962, 0, hw, H, 1.0, .5, .5);
  veil(); const gl = ctx.createLinearGradient(0, 100, 0, 540); gl.addColorStop(0, 'rgba(14,14,12,0)'); gl.addColorStop(.25, 'rgba(14,14,12,.6)'); gl.addColorStop(1, 'rgba(14,14,12,0)'); ctx.fillStyle = gl; ctx.fillRect(0, 100, W, 440);
  ctx.fillStyle = C.honey; ctx.fillRect(958, 0, 4, H * eo(seg(t, s.a - .1, s.a + .15)));
  const cols = [[120, '死掉', C.loss, 1305540, 'Lost'], [1082, '补上', C.honey, 1453600, 'Added']];
  cols.forEach(([x, lab, col, v, en], i) => {
    const t0 = s.a + .2 + i * .15, k = eo(seg(t, t0, t0 + .2)); if (k <= 0) return;
    ctx.save(); ctx.globalAlpha = k;
    const wl = tw(lab, `900 54px ${F.zh9}`) + 36; ctx.fillStyle = col; ctx.fillRect(x, 170, wl, 76); text(lab, x + 18, 229, `900 54px ${F.zh9}`, C.bg);
    text(en, x + wl + 18, 222, `800 30px ${F.n8}`, col);
    const kr = eo(seg(t, s.a + .35, s.a + 1.9)), wn = num(fmt(v * kr), x, 372, 100, kr >= 1 ? col : C.ink);
    text('箱', x + wn + 14, 366, `900 50px ${F.zh9}`, C.ink);
    ctx.restore();
    TX.push({ id: 'split' + i, text: lab + fmt(v) + '箱', x0: x, y0: 160, x1: x + 680, y1: 400 });
  });
  const kc = eo(seg(t, s.a + .6, s.a + .8)); if (kc > 0) {
    ctx.save(); ctx.globalAlpha = kc; const lab = '2025 · 四个季度相加', w = tw(lab, `900 26px ${F.zh9}`) + 36;
    ctx.fillStyle = C.bg; ctx.fillRect(960 - w / 2, 60, w, 48); text(lab, 960, 94, `900 26px ${F.zh9}`, C.ink, 'center'); ctx.restore();
    TX.push({ id: 'splitN', text: lab, x0: 960 - w / 2, y0: 60, x1: 960 + w / 2, y1: 108 });
  }
  if (t > s.a + 1.95) {   // the difference, on the beat after the counters settle
    const k = seg(t, s.a + 1.95, s.a + 2.1); ctx.save(); ctx.translate(1082, 410); ctx.scale(lerp(1.3, 1, back(k)), lerp(1.3, 1, back(k))); ctx.globalAlpha = clamp(k * 3);
    ctx.fillStyle = 'rgba(14,14,12,.82)'; ctx.fillRect(0, 0, 330, 64); text('多补', 20, 46, `900 34px ${F.zh9}`, C.honey); num('148,060', 110, 47, 40, C.ink); text('箱', 290, 46, `900 30px ${F.zh9}`, C.ink); ctx.restore();
    TX.push({ id: 'splitD', text: '多补148,060', x0: 1082, y0: 410, x1: 1522, y1: 474 });
  }
  sourceTag(t, s.a + .3);
}
// 23.5–27.5 s: three ways to rebuild, in a three-panel grid; each panel lights up as the voice names it
function shotGrid(s, t) {
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  const PW = 632, G = 12, xs = [0, PW + G, 2 * (PW + G)];
  const g1 = frame('g1', 124, t, s.a), pk = img('assets/img/package.jpg'), qn = img('assets/img/queen.jpg');
  const hit = [23.78, 24.82, 25.96];
  const labs = [['新建', 'raise new ones'], ['整箱买', 'buy them whole'], ['换蜂王', 'requeen']];
  for (let i = 0; i < 3; i++) {
    const t0 = s.a - .14 + i * .1, k = eo(seg(t, t0, t0 + .28)), y = (1 - k) * 260, x = xs[i];
    ctx.save(); ctx.globalAlpha = clamp(k * 1.5); ctx.translate(0, y);
    const z = 1 + .03 * seg(t, s.a, s.b), on = t >= hit[i], dim = on ? '' : ' brightness(.6) saturate(.6)';
    if (i === 0) plate(g1, x, 0, PW, H, z, .5, .5, GRADE + dim);
    if (i === 1) photo(pk, .64 * z, 720, 980, x + PW / 2, 540, GRADE + dim, [x, 0, PW, H]);
    if (i === 2) { photo(qn, .9 * z, 930, 740, x + PW / 2, 600, GRADE + dim, [x, 0, PW, H]); if (on) { const kq = eo(seg(t, hit[2] + .1, hit[2] + .4)); ctx.strokeStyle = C.honey; ctx.lineWidth = 5; ctx.beginPath(); ctx.arc(x + PW / 2 + (-5) * .9 * z, 600 + (-20) * .9 * z, 110, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * kq); ctx.stroke(); } }
    if (on) { const kf = 1 - seg(t, hit[i], hit[i] + .3); ctx.strokeStyle = `rgba(255,194,26,${.5 + .5 * kf})`; ctx.lineWidth = 8; ctx.strokeRect(x + 4, 4, PW - 8, H - 8); }
    ctx.restore();
  }
  veil();
  for (let i = 0; i < 3; i++) {
    const t0 = s.a - .14 + i * .1, k = eo(seg(t, t0, t0 + .28)), y = (1 - k) * 260, x = xs[i], on = t >= hit[i];
    ctx.save(); ctx.globalAlpha = clamp(k * 1.5); ctx.translate(0, y);
    // label at the top of the panel
    const lx = x + 40, ly = 250;
    ctx.fillStyle = on ? C.honey : 'rgba(14,14,12,.78)'; const wl = tw(labs[i][0], `900 56px ${F.zh9}`) + 40; ctx.fillRect(lx, ly - 58, wl, 78);
    text(labs[i][0], lx + 20, ly + 2, `900 56px ${F.zh9}`, on ? C.bg : C.ink);
    num(String(i + 1), lx, ly - 76, 30, C.honey);
    ctx.fillStyle = 'rgba(14,14,12,.72)'; const we = tw(labs[i][1], `500 26px ${F.n5}`) + 24; ctx.fillRect(lx, ly + 28, we, 40); text(labs[i][1], lx + 12, ly + 57, `500 26px ${F.n5}`, C.ink);
    ctx.restore();
    if (k >= 1) TX.push({ id: 'grid' + i, text: labs[i][0], x0: lx, y0: ly - 80, x1: lx + 300, y1: ly + 70 });
  }
}
// 27.5–30.5 s: pull quote — the report's own sentence, highlighted
function shotQuote(s, t) {
  paper(t, s, .78, .86, 300, 528, .01, [[27.75, 36, 508.7, 433.7, 521.0, .4], [28.3, 36, 534.1, 569.6, 546.3, .5], [28.8, 36, 546.7, 62, 558.9, .12]]); veil();
  const k = eo(seg(t, 28.1, 28.3)); ctx.save(); ctx.globalAlpha = k; text('“', 150, 560, `900 300px ${F.n8}`, C.honey); ctx.restore();
  sourceTag(t, s.a + .1, 'USDA NASS · 第 1 页');
}
// 30.5–33 s: the culprit — scanning electron micrograph, punch in on "varroa mites", circle callout
function shotSem(s, t) {
  const im = img('assets/img/sem.jpg'); const tp = 30.6, k = eo(seg(t, tp, tp + .32));
  const sc = lerp(.8, 1.0, k) + .04 * seg(t, tp + .32, s.b), mx = 1810, my = 800;
  const fx = lerp(1200, mx, k), fy = lerp(855, my - 20, k);
  const P = photo(im, sc, fx, fy, W / 2, H / 2 - 40); veil();
  const kr = seg(t, tp + .3, tp + .6);
  if (kr > 0) {
    const px = P.dx + mx * sc, py = P.dy + my * sc, r = 360 * sc;
    ctx.save(); ctx.strokeStyle = C.honey; ctx.lineWidth = 6; ctx.beginPath(); ctx.arc(px, py, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * eo(kr)); ctx.stroke();
    const kl = eo(seg(t, tp + .3, tp + .5)); ctx.globalAlpha = kl;
    const ax = px - r * .74, ay = py - r * .66, bx = ax - 120, by = ay - 90;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.lineTo(bx - 260, by); ctx.stroke();
    text('瓦螨', bx - 260, by - 22, `900 72px ${F.zh9}`, C.ink); text('Varroa destructor', bx - 258, by + 40, `600 30px ${F.it}`, C.dim);
    ctx.restore();
    if (t > tp + .3) TX.push({ id: 'mite', text: '瓦螨', x0: bx - 262, y0: by - 100, x1: bx + 10, y1: by });
  }
  flash(t, tp, .08);
}
// 33–37.5 s: what hurts the colonies — one long bar and five short ones (a held judgement frame)
const STRESS = [['瓦螨', 21.8, 'Varroa mites'], ['农药', 6.4, 'Pesticides'], ['其他虫害', 5.6, 'Other pests & parasites'], ['疾病', 4.8, 'Diseases'], ['原因不明', 4.6, 'Unknown'], ['其他', 3.5, 'Other']];
function shotStress(s, t) {
  ledger(t, s.a); ctx.save(); camPush(t, s.a, s.b, 1, 1.025, 900, 470);
  text('谁在伤害蜂群', 120, 236, `900 64px ${F.zh9}`, C.ink); text('Share of colonies affected, Jan–Mar 2026', 122, 286, `500 24px ${F.n5}`, C.grey);
  const bx = 470, ppx = 1200 / 22, y0 = 360, rh = 84;
  STRESS.forEach(([lab, v, en], i) => {
    const t0 = s.a + .25 + (i === 0 ? 0 : .35 + i * .08), k = eio(seg(t, t0, t0 + (i === 0 ? .6 : .3))), y = y0 + i * rh;
    if (t < t0) return;
    text(lab, bx - 30, y + 36, `900 ${i === 0 ? 44 : 34}px ${F.zh9}`, i === 0 ? C.honey : C.ink, 'right');
    ctx.fillStyle = i === 0 ? C.honey : '#5E5C55'; ctx.fillRect(bx, y + 2, v * ppx * k, i === 0 ? 56 : 44);
    if (k > .5) num(v.toFixed(1) + '%', bx + v * ppx * k + 18, y + 42, i === 0 ? 46 : 32, i === 0 ? C.honey : C.dim);
    TX.push({ id: 'st' + i, text: lab + v.toFixed(1) + '%', x0: 150, y0: y - 10, x1: bx + v * ppx + 200, y1: y + 60 });
  });
  ctx.restore();
  veil('c'); sourceTag(t, s.a + .3, 'USDA NASS · 第 13 页');
  TX.push({ id: 'stressT', text: '谁在伤害蜂群', x0: 110, y0: 170, x1: 560, y1: 250 });
}
// 37.5–41.5 s: share lost each quarter — flat at 11–12 %, then the spike
const QL = [['1–3月', 12, '2025'], ['4–6月', 11], ['7–9月', 11], ['10–12月', 12], ['1–3月', 16, '2026'], ['4–6月', 11]];
function shotLoss(s, t) {
  ledger(t, s.a); ctx.save(); camPush(t, s.a, s.b, 1, 1.03, 1300, 420);
  text('每季度损失率', 120, 236, `900 64px ${F.zh9}`, C.ink); text('Share of colonies lost each quarter, U.S.', 122, 286, `500 24px ${F.n5}`, C.grey);
  const x0 = 700, x1 = 1720, yb = 770, yt = 300, X = i => lerp(x0, x1, i / 5), Y = v => lerp(yb, yt, v / 20);
  ctx.lineWidth = 2; [0, 10, 20].forEach(v => { ctx.strokeStyle = 'rgba(255,255,255,.1)'; ctx.beginPath(); ctx.moveTo(x0 - 60, Y(v)); ctx.lineTo(x1 + 50, Y(v)); ctx.stroke(); text(v + '%', x0 - 76, Y(v) + 9, `500 24px ${F.n5}`, C.grey, 'right'); });
  QL.forEach(([m, , y], i) => { text(m, X(i), yb + 44, `500 25px ${F.zh5}`, i === 4 ? C.loss : C.grey, 'center'); if (y) text(y, X(i), yb + 86, `800 24px ${F.n8}`, C.grey, 'center'); });
  const kd = eio(seg(t, s.a + .2, s.a + 2.4)) * 5;   // the line reaches the spike on the voice's "sixteen"
  ctx.lineWidth = 7; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  for (let i = 0; i < 5; i++) { const f = clamp(kd - i); if (f <= 0) break; ctx.strokeStyle = (i === 3 || i === 4) ? C.loss : C.ink; ctx.beginPath(); ctx.moveTo(X(i), Y(QL[i][1])); ctx.lineTo(lerp(X(i), X(i + 1), f), lerp(Y(QL[i][1]), Y(QL[i + 1][1]), f)); ctx.stroke(); }
  QL.forEach(([, v], i) => { if (kd < i - .02) return; ctx.fillStyle = i === 4 ? C.loss : C.ink; ctx.beginPath(); ctx.arc(X(i), Y(v), i === 4 ? 14 : 9, 0, 7); ctx.fill(); if (i !== 4) num(v + '%', X(i), Y(v) - 26, 32, C.ink, 'center'); });
  const tp = 39.75;
  if (t > tp) {
    const k = back(seg(t, tp, tp + .16)), pr = seg(t, tp, tp + .7);
    ctx.save(); ctx.strokeStyle = `rgba(255,74,61,${1 - pr})`; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(X(4), Y(16), 14 + pr * 80, 0, 7); ctx.stroke();
    ctx.translate(X(4), Y(16) - 46); ctx.scale(k, k); num('16%', 0, 0, 110, C.loss, 'center'); ctx.restore();
    const k2 = eo(seg(t, tp + .25, tp + .45)); ctx.save(); ctx.globalAlpha = k2; ctx.fillStyle = C.loss; const lab = '六个季度最高', w = tw(lab, `900 30px ${F.zh9}`) + 28;
    ctx.fillRect(X(4) + 70, Y(16) - 20, w, 46); text(lab, X(4) + 84, Y(16) + 13, `900 30px ${F.zh9}`, C.ink); ctx.restore();
    TX.push({ id: 'loss16', text: '16%', x0: X(4) - 120, y0: Y(16) - 150, x1: X(4) + 120, y1: Y(16) - 30 });
  }
  ctx.restore();
  veil('c'); sourceTag(t, s.a + .3);
  TX.push({ id: 'lossT', text: '每季度损失率', x0: 110, y0: 170, x1: 560, y1: 250 });
}
// 41.5–45 s: where — state loss rates, push to California; the photo grows out of California's outline
const RATE = { California: 18, Florida: 15, Georgia: 17, Idaho: 15, Iowa: 4, Louisiana: 8, Michigan: 5, Minnesota: 2, Mississippi: 7, Montana: 0, 'New York': 17, 'North Carolina': 18, 'North Dakota': 2, Ohio: 7, Oregon: 7, Pennsylvania: 23, 'South Dakota': 1, Texas: 11, Washington: 2, Wisconsin: 8 };
const rateCol = v => v == null ? '#2A2925' : v >= 20 ? '#FF4A3D' : v >= 15 ? '#E0573F' : v >= 10 ? '#A9503D' : v >= 5 ? '#6E4136' : '#4A3530';
const MAP = { x: 650, y: 170, k: 1.12 };
function statePath(st, k = MAP.k, ox = MAP.x, oy = MAP.y) { ctx.beginPath(); for (const r of st.rings) { r.forEach(([x, y], j) => j ? ctx.lineTo(ox + x * k, oy + y * k) : ctx.moveTo(ox + x * k, oy + y * k)); ctx.closePath(); } }
function shotMap(s, t) {
  ledger(t, s.a, true);
  const ca = STATES.states.find(x => x.name === 'California'), cx = MAP.x + ca.c[0] * MAP.k, cy = MAP.y + ca.c[1] * MAP.k;
  const kz = eio(seg(t, 43.6, 44.9)), z = lerp(1, 2.1, kz);
  ctx.save(); ctx.translate(lerp(0, W * .5 - cx, kz), lerp(0, H * .45 - cy, kz)); ctx.translate(cx, cy); ctx.scale(z, z); ctx.translate(-cx, -cy);
  STATES.states.forEach((st, i) => {
    const v = RATE[st.name], t0 = s.a + .15 + (st.c[0] / 1000) * .5, k = eo(seg(t, t0, t0 + .2));
    statePath(st); ctx.fillStyle = rateCol(v); ctx.globalAlpha = .25 + .75 * k; ctx.fill(); ctx.globalAlpha = 1;
    ctx.strokeStyle = 'rgba(14,14,12,.9)'; ctx.lineWidth = 1.6 / z; ctx.stroke();
  });
  const kc = eo(seg(t, 42.3, 42.5));
  if (kc > 0) { statePath(ca); ctx.strokeStyle = C.honey; ctx.lineWidth = 5 / z; ctx.globalAlpha = kc; ctx.stroke(); ctx.globalAlpha = 1; }
  ctx.restore();
  veil('c');
  // legend + title (stay put while the map pushes)
  const kf = 1 - eio(seg(t, 43.6, 44.0));
  text('各州损失率', 120, 236, `900 64px ${F.zh9}`, C.ink);
  ctx.save(); ctx.globalAlpha = kf;
  ctx.fillStyle = C.ink; ctx.fillRect(122, 262, 150, 42); num('2026 Q1', 197, 293, 26, C.bg, 'center');
  text('Share of colonies lost, Jan–Mar', 290, 292, `500 24px ${F.n5}`, C.grey);
  [['0–5%', 2], ['5–10%', 7], ['10–15%', 12], ['15–20%', 17], ['20%+', 23]].forEach(([l, v], i) => { ctx.fillStyle = rateCol(v); ctx.fillRect(122, 360 + i * 50, 40, 34); text(l, 178, 387 + i * 50, `500 24px ${F.n5}`, C.dim); });
  ctx.fillStyle = rateCol(null); ctx.fillRect(122, 610, 40, 34); text('未单列', 178, 637, `500 24px ${F.zh5}`, C.dim);
  ctx.restore();
  if (t < 44.9) TX.push({ id: 'mapT', text: '各州损失率', x0: 110, y0: 170, x1: 460, y1: 250 }); if (kf > .99) TX.push({ id: 'mapQ', text: '2026 Q1', x0: 120, y0: 260, x1: 280, y1: 306 });
  // California label (screen space, follows the push through the same transform)
  if (kc > 0) {
    const sx = lerp(cx, W * .5, kz), sy = lerp(cy, H * .45, kz);
    ctx.save(); ctx.globalAlpha = kc * (1 - seg(t, 44.85, 45.0)); ctx.strokeStyle = C.honey; ctx.lineWidth = 4;
    const lx = sx + 150 + kz * 120, ly = sy - 170;
    ctx.beginPath(); ctx.moveTo(sx + 20, sy - 20); ctx.lineTo(lx - 20, ly + 20); ctx.lineTo(lx + 330, ly + 20); ctx.stroke();
    text('加州', lx, ly - 6, `900 52px ${F.zh9}`, C.ink); num('−220,000', lx + 128, ly - 6, 46, C.honey);
    text('损失率 18%', lx, ly + 66, `900 30px ${F.zh9}`, C.dim); ctx.restore();
    if (t < 44.85) TX.push({ id: 'ca', text: '加州−220,000', x0: lx - 10, y0: ly - 70, x1: lx + 400, y1: ly + 30 });
  }
  // mask transition: the almond-orchard photo grows out of California's outline
  const km = ei(seg(t, 44.9, 45.5));
  if (km > 0) {
    const im = img('assets/img/almond.jpg');
    const sx = W * .5, sy = H * .45, kk = MAP.k * z * lerp(1, 14, km);
    ctx.save(); ctx.beginPath(); for (const r of ca.rings) { r.forEach(([x, y], j) => { const X = sx + (x - ca.c[0]) * kk, Y = sy + (y - ca.c[1]) * kk; j ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); }); ctx.closePath(); } ctx.clip();
    photo(im, .76, 1150, 900); ctx.restore();
  }
  sourceTag(t, s.a + .3, 'USDA NASS · 第 7 页');
}
function shotAlmond(s, t) {
  const im = img('assets/img/almond.jpg'); photo(im, lerp(.76, .8, eio(seg(t, s.a, s.b))), 1150, 900); veil();
}
// end card: title, rule, style name, sign-off, sources (library demo only)
function shotEnd(s, t) {
  const im = frame('ed', 153, t, s.a); const kd = eo(seg(t, s.a, s.a + .4));
  plate(im, 0, 0, W, H, lerp(1.0, 1.04, seg(t, s.a, s.b)), .6, .5, `${GRADE} blur(${8 * kd}px) brightness(${1 - .55 * kd})`);
  const g = ctx.createLinearGradient(0, 0, W * .7, 0); g.addColorStop(0, 'rgba(14,14,12,.85)'); g.addColorStop(1, 'rgba(14,14,12,0)'); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  const L = 120, k1 = seg(t, s.a + .15, s.a + .3);
  if (t > s.a + .15) { ctx.save(); ctx.translate(L, 330); const sc = lerp(1.3, 1, back(k1, 1.5)); ctx.scale(sc, sc); ctx.globalAlpha = clamp(k1 * 3); text('蜜蜂账本', 0, 0, `900 150px ${F.zh9}`, C.ink); ctx.restore(); }
  const k2 = eo(seg(t, s.a + .3, s.a + .5)); ctx.save(); ctx.globalAlpha = k2;
  text('The Bee Ledger', L + 4, 418, `800 62px ${F.n8}`, C.honey);
  ctx.fillStyle = 'rgba(247,245,239,.5)'; ctx.fillRect(L + 4, 462, 720 * eo(seg(t, s.a + .4, s.a + .8)), 2);
  text('CAPTION NEWS', L + 4, 528, `800 32px ${F.n8}`, C.ink); text('· 字幕新闻', L + 4 + tw('CAPTION NEWS', `800 32px ${F.n8}`) + 14, 528, `900 32px ${F.zh9}`, C.ink);
  text('LemoLab × Claude Opus 5.5', L + 4, 584, `500 32px ${F.n5}`, C.dim);
  ctx.restore();
  const k3 = eo(seg(t, s.a + .6, s.a + .9)); ctx.save(); ctx.globalAlpha = k3 * .92;
  const CR = [
    '数据 Data: USDA NASS, Honey Bee Colonies (Aug 3, 2026), operations with 5+ colonies; 2025 losses and additions are four quarters summed — public domain',
    'Video: "Te veel bijen in de Biesbosch…" by Altena TV, CC BY 3.0 · "Apis mellifera flying x40 SlowMotion01" by Phonon.b, CC BY 4.0',
    'Video: "Slow Motion Bee Flight – Close-up video of honey bees" by Martin J. Calabrese, CC BY 3.0 · "Bees flying in HD in slow motion" by Midsummer Bees, CC BY 3.0',
    'Photo: "Three bee packages for Park" by vastateparksstaff, CC BY 2.0 · Sound: "Рій на землі 02" by Сарапулов, CC BY 4.0 · Drums: "MuldjordKit" by Lars Muldjord, CC BY 4.0',
    'Public domain: USDA (apiary video, almond photo), USDA ARS (micrograph), USGS (queen photo), Natural Earth (map) · All via Wikimedia Commons, cropped and colour-graded',
  ];
  CR.forEach((l, i) => text(l, L + 4, 860 + i * 34, `500 20px ${F.n5}`, C.dim));
  ctx.restore();
  if (t > s.a + .3) { TX.push({ id: 'endT', text: '蜜蜂账本', x0: L, y0: 200, x1: 760, y1: 350 }); TX.push({ id: 'endE', text: 'The Bee Ledger', x0: L, y0: 360, x1: 760, y1: 430 }); TX.push({ id: 'endS', text: 'CAPTION NEWS · 字幕新闻', x0: L, y0: 490, x1: 760, y1: 540 }); TX.push({ id: 'endL', text: 'LemoLab × Claude Opus 5.5', x0: L, y0: 550, x1: 760, y1: 600 }); }
}

// ---------- main render ----------
let TX = [];
function draw(t) {
  TX = []; ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.filter = 'none';
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  const s = shotAt(t);
  if (s.k === 'vid') shotVid(s, t);
  else if (s.k === 'sting') shotSting(s, t);
  else if (s.k === 'half') shotHalf(s, t);
  else if (s.k === 'freeze') shotFreeze(s, t);
  else if (s.k === 'doc6') shotDoc6(s, t);
  else if (s.k === 'stock') shotStock(s, t);
  else if (s.k === 'split') shotSplit(s, t);
  else if (s.k === 'grid') shotGrid(s, t);
  else if (s.k === 'quote') shotQuote(s, t);
  else if (s.k === 'sem') shotSem(s, t);
  else if (s.k === 'stress') shotStress(s, t);
  else if (s.k === 'loss') shotLoss(s, t);
  else if (s.k === 'map') shotMap(s, t);
  else if (s.k === 'almond') shotAlmond(s, t);
  else if (s.k === 'end') shotEnd(s, t);
  if (s.k !== 'end') credit(s.cr);
  hook(t);
  for (const c of CAPS) capCard(c, t);
  if (s.k !== 'end') bug(t);
}

window.DUR = DUR;
async function render(t) {
  NEED.clear(); draw(t);
  if (NEED.size) { await Promise.all([...NEED].map(load)); NEED.clear(); draw(t); }
}
window.render = render;
window.TEXTS = () => TX;
function buildEV() { return [
  ...SHOTS.map(s => ({ t: s.a, type: 'cut', k: s.k })),
  ...CAPS.flatMap(c => c[2].split('|').map((_, i) => ({ t: +(c[0] + .04 + i * .12).toFixed(3), type: 'slam', big: c[4] || 1 }))),
  { t: 0.06, type: 'slam' }, { t: 0.13, type: 'hook' }, { t: 0.4, type: 'slam' }, { t: 0.13, type: 'rattle', d: .47 },
  { t: 4.62, type: 'whoosh' }, { t: 5.0, type: 'sting' }, { t: 5.18, type: 'slam', big: 1.5 }, { t: 5.5, type: 'tick' }, { t: 7.18, type: 'whoosh' },
  { t: 7.92, type: 'swipe', d: .42 }, { t: 8.28, type: 'slam' },
  { t: 11.0, type: 'shutter' }, { t: 13.0, type: 'hit' }, { t: 13.28, type: 'marker', d: .45 }, { t: 14.25, type: 'stamp' },
  { t: 16.0, type: 'whoosh' }, { t: 16.2, type: 'draw', d: 1.0 }, { t: 17.05, type: 'pop' },
  { t: 19.0, type: 'whoosh' }, { t: 19.35, type: 'rattle', d: 1.55 }, { t: 20.95, type: 'ding' },
  { t: 23.5, type: 'whoosh' }, { t: 23.78, type: 'pop' }, { t: 24.82, type: 'pop' }, { t: 25.96, type: 'pop' },
  { t: 27.5, type: 'paper' }, { t: 27.75, type: 'marker', d: .4 }, { t: 28.3, type: 'marker', d: .5 },
  { t: 30.6, type: 'punch' }, { t: 30.9, type: 'pop' },
  { t: 33.0, type: 'whoosh' }, { t: 33.25, type: 'draw', d: .6 },
  { t: 37.5, type: 'whoosh' }, { t: 37.7, type: 'draw', d: 2.2 }, { t: 39.75, type: 'ding' },
  { t: 41.5, type: 'whoosh' }, { t: 41.65, type: 'ticks', d: .7 }, { t: 42.3, type: 'pop' }, { t: 43.6, type: 'riser', d: 1.6 }, { t: 44.9, type: 'whoosh' },
  { t: 46.6, type: 'swipe', d: .22 }, { t: 49.0, type: 'ding' },
  { t: 50.0, type: 'silence', d: .5 }, { t: 50.5, type: 'hit' }, { t: 54.5, type: 'end' },
].sort((a, b) => a.t - b.t); }
(async () => {
  await Promise.all([[900, 'SC9'], [500, 'SC5'], [800, 'IT8'], [500, 'IT5']].map(([w, f]) => document.fonts.load(`${w} 40px ${f}`)));
  await document.fonts.load(`italic 600 40px IT6I`);
  STATES = await (await fetch('assets/states.json')).json();
  TL = await (await fetch('timeline.json')).json(); VO = TL.vo; HOOK_CUE = [TL.hook.t0, TL.hook.t1, TL.hook.zh, TL.hook.en];
  CAPS = TL.caps.map(c => [c.t0, c.t1, c.zh, c.en, c.big || 1]); window.EV = buildEV();
  await Promise.all(['doc1', 'sem', 'almond', 'package', 'queen'].map(n => load(`assets/img/${n}.jpg`)));
  await render(0); window.READY = true;
})();

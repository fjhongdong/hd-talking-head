"""Frame-by-frame compositing: shot list → white balance → grid / split screen / crowd light trails → unified grade (film curve + desaturation + warm tone + bloom) → text → grain + 1.85:1 letterbox.
Usage: python tools/render.py out/picture.mp4
      python tools/render.py --still sec out.jpg [sec out.jpg …]   (grab stills: style frames, spot-checking transitions)
A full render also writes work/texts.json (the frames and box of each on-screen text) for readcheck (demo/index.html reads it)."""
import os, sys, subprocess, math, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.chdir(os.path.join(HERE, '..'))
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from shots import SHOTS, CLIPS, FLASH_SRC, FLASH_LEN, GRID_STAGES, POOL, NIGHT_SRC
from timeline import FPS, DUR, bar, BEAT, NOON, GRID, BRAKE, DUSK, FLASH, STOP, PAGE, CARD, SLATE

W, H = 1920, 1080
NF = round(DUR * FPS)
rng = np.random.default_rng(1982)
F_LAT = 'fonts/Michroma-Regular.ttf'
F_SC = 'fonts/NotoSansSC-VF.ttf'

INK = (237, 232, 223)        # warm white
DIM = (176, 170, 160)        # English secondary line
SODIUM = (217, 119, 47)      # sodium-lamp orange: the only accent colour in the whole film

# ───────── grade ─────────
def make_luts():
    x = np.linspace(0, 1, 256)
    s = 1 / (1 + np.exp(-6.2 * (x - .47))); s = (s - s[0]) / (s[-1] - s[0])
    y = .55 * s + .45 * x
    y = .028 + .955 * y
    r = np.clip(y * 1.025 + .004, 0, 1); g = np.clip(y, 0, 1); b = np.clip(y * .965 + .01 * (1 - x), 0, 1)
    return [(c * 255 + .5).astype(np.uint8) for c in (r, g, b)]


LUT = make_luts()
SAT = .86


def wb_gains(img, strength):
    if strength <= 0: return np.ones(3, np.float32)
    a = img[::8, ::8].astype(np.float32) / 255; l = a.mean(2); m = (l > .12) & (l < .88)
    if m.sum() < 500: return np.ones(3, np.float32)
    mean = a[m].mean(0); g = mean.mean() / np.maximum(mean, 1e-3)
    return (g ** strength).astype(np.float32)


def grade(a, bloom=.10):
    l = a @ np.array([.2126, .7152, .0722], np.float32)
    a = l[..., None] + SAT * (a - l[..., None])
    a = np.clip(a, 0, 255).astype(np.uint8)
    out = np.stack([LUT[c][a[..., c]] for c in range(3)], 2).astype(np.float32)
    small = Image.fromarray(out.astype(np.uint8)).resize((W // 8, H // 8), Image.BILINEAR)
    hl = np.clip(np.asarray(small).astype(np.float32) - 170, 0, None) * 1.6
    hl = np.asarray(Image.fromarray(hl.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BILINEAR)).astype(np.float32)
    return out + bloom * hl * np.array([1.0, .82, .62], np.float32)


LB = round((H - W / 1.85) / 2)   # 21 px letterbox
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
VIG = (1 - .16 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.3).clip(.6, 1)[..., None]
GRAIN = []
for k in range(10):
    n = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
    im = Image.fromarray(((n * 40) + 128).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(.6))
    GRAIN.append(((np.asarray(im).astype(np.float32) - 128) / 40)[..., None])


def finish(out, f):
    l = out.mean(2, keepdims=True) / 255
    out = out * VIG + GRAIN[(f * 7) % len(GRAIN)] * (9.0 * (0.35 + 1.3 * l * (1 - l)))
    out[:LB] = 0; out[H - LB:] = 0
    return np.clip(out, 0, 255).astype(np.uint8)


# ───────── motion ─────────
_wn = rng.normal(0, 1, (NF + 40, 2)); _k = np.exp(-np.linspace(-2, 2, 15) ** 2); _k /= _k.sum()
weave = np.stack([np.convolve(_wn[:, j], _k, 'same') for j in range(2)], 1) * 1.1      # ±0.5 px gate weave


def ease(u): u = min(1, max(0, u)); return u * u * (3 - 2 * u)


def move(img, s, dx, dy, f, size=(W, H)):
    w, h = size; wx, wy = weave[f]
    if abs(s - 1) < 1e-4 and abs(dx) + abs(dy) + abs(wx) + abs(wy) < .05: return img
    cx, cy = w / 2 - dx - wx, h / 2 - dy - wy
    inv = (1 / s, 0, cx - w / 2 / s, 0, 1 / s, cy - h / 2 / s)
    return np.asarray(Image.fromarray(img).transform((w, h), Image.AFFINE, inv, Image.BICUBIC))


# ───────── source loading ─────────
class Reader:
    def __init__(self, cid, skip=0):
        w, h = CLIPS[cid]['size']; self.w, self.h = w, h
        self.p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', f'work/clips/{cid}.mp4', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
        self.last = None
        for _ in range(skip): self.next()

    def next(self):
        b = self.p.stdout.read(self.w * self.h * 3)
        if len(b) == self.w * self.h * 3: self.last = np.frombuffer(b, np.uint8).reshape(self.h, self.w, 3)
        return self.last

    def close(self):
        self.p.stdout.close(); self.p.wait()


def load_clip(cid, size=None):
    r = Reader(cid); fr = []
    while True:
        a = r.next()
        if a is None or (fr and a is fr[-1][1]): break
        fr.append((None, a))
        if len(fr) >= CLIPS[cid]['n']: break
    r.close(); fr = [a for _, a in fr]
    if size: fr = [np.asarray(Image.fromarray(a).resize(size, Image.BILINEAR)) for a in fr]
    return fr


_photo = {}


def photo_src(name):
    if name not in _photo: _photo[name] = Image.open(f'raw/{name}.jpg').convert('RGB')
    return _photo[name]


def photo_frame(name, c, s):
    """16:9 crop of a photo; s = zoom (1 = the largest 16:9 box that fits in the photo)"""
    im = photo_src(name)
    cw = min(im.width, im.height * 16 / 9) / s; ch = cw * 9 / 16
    cx = np.clip(c[0] * im.width, cw / 2, im.width - cw / 2); cy = np.clip(c[1] * im.height, ch / 2, im.height - ch / 2)
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return np.asarray(im.transform((W, H), Image.EXTENT, box, Image.BICUBIC))


def orbit_scale(t):
    """Opening: 0–0.45 s slams in from the whole photo, 1.0 → 1.5 (expo-out, with shutter blur), then keeps accelerating in toward Manhattan"""
    if t < .45:
        u = t / .45; return 1.0 + .5 * (1 - (1 - u) ** 3)
    u = (t - .45) / (4.0 - .45); return 1.5 + .6 * u * u


def page_frame(i, n):
    im = photo_src('lg380'); pw, ph = im.size
    u = ease(i / max(1, n - 1))
    s = 1.06 + .5 * u
    cw = pw / s; ch = cw * 9 / 16
    cx = pw * (.50 + .01 * u); cy = ph * (.78 + .065 * u)
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    fr = np.asarray(im.transform((W, H), Image.EXTENT, box, Image.BICUBIC)).astype(np.float32)
    g = (1.05 - .55 * ((xx / W) * .6 + (yy / H) * .4))[..., None]
    ly = (ph * .850 - box[1]) / ch * H            # "Just as any of you is one of a living crowd, I was one of a crowd,"
    band = np.exp(-((yy - ly) / (95 * (1 + .5 * u))) ** 2)[..., None] * (.38 * min(1, i / (n * .45)))
    return fr * (g + band) * np.array([1.0, .93, .80], np.float32)


# ───────── crowds / traffic → light trails ─────────
class Trails:
    """Crowd as graphics (locked-off camera): background = per-pixel median over the whole clip; a connected blob that differs strongly from the background = one pedestrian (scipy connected components, take the centroid),
    matched frame to frame by nearest neighbour into tracks, drawn as sodium-orange dots + thin lines, old lines decaying per frame; the underlying picture is darkened and desaturated so the lines float out."""
    def __init__(self, cid):
        fr = load_clip(cid, (W // 2, H // 2))
        lum = np.stack([a.astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32) for a in fr])
        self.bg = np.median(lum, 0); self.prev = []
        self.canvas = Image.new('L', (W, H), 0)

    def __call__(self, plate, i, n):
        from scipy import ndimage
        sm = np.asarray(Image.fromarray(plate.clip(0, 255).astype(np.uint8)).resize((W // 2, H // 2), Image.BILINEAR)).astype(np.float32)
        lum = sm @ np.array([.2126, .7152, .0722], np.float32)
        d = ndimage.gaussian_filter(np.abs(lum - self.bg), 1.2)
        lab, k = ndimage.label(d > 22)
        pts = []
        if k:
            area = ndimage.sum(np.ones_like(d), lab, range(1, k + 1))
            cen = ndimage.center_of_mass(d, lab, range(1, k + 1))
            pts = [(cx * 2, cy * 2) for (cy, cx), ar in zip(cen, area) if 8 <= ar <= 900 and cy > H * .18]
        # decay old lines, draw new lines and dots
        self.canvas = Image.eval(self.canvas, lambda v: int(v * .9))
        dr = ImageDraw.Draw(self.canvas)
        for (x, y) in pts:
            if self.prev:
                q = min(self.prev, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
                if (q[0] - x) ** 2 + (q[1] - y) ** 2 < 70 ** 2: dr.line([q, (x, y)], fill=255, width=2)
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=255)
        self.prev = pts
        tr = np.asarray(self.canvas.filter(ImageFilter.GaussianBlur(.8))).astype(np.float32)[..., None] / 255
        kk = ease((i / FPS - .15) / .4)                # first see the original picture clearly, then it turns into lines
        L = (plate @ np.array([.2126, .7152, .0722], np.float32))[..., None]
        base = plate * (1 - kk) + (L * .32 + plate * .08) * kk
        return base * (1 - tr * kk) + np.array(SODIUM, np.float32) * 1.35 * tr * kk


# ───────── text ─────────
_fonts = {}


def font(path, size, wght=None):
    key = (path, size, wght)
    if key not in _fonts:
        f = ImageFont.truetype(path, size)
        if wght is not None:
            try: f.set_variation_by_axes([wght])
            except Exception: pass
        _fonts[key] = f
    return _fonts[key]


def tracked_w(d, text, fnt, track):
    return sum(d.textlength(ch, font=fnt) + track * fnt.size for ch in text) - track * fnt.size


class Layer:
    """One frame's text layer + readcheck records (only records text that is fully opaque and settled)"""
    def __init__(self):
        self.im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); self.d = ImageDraw.Draw(self.im); self.rec = []

    def text(self, tid, x, y, text, fnt, col, track=0.0, a=1.0, final=True):
        if a <= 0.004: return
        cx = x
        for ch in text:
            self.d.text((cx, y), ch, font=fnt, fill=col + (int(255 * a),))
            cx += self.d.textlength(ch, font=fnt) + track * fnt.size
        if a >= .98 and final:
            bb = self.d.textbbox((x, y), text, font=fnt)
            self.rec.append(dict(id=tid, text=text, x0=x, y0=bb[1], x1=x + tracked_w(self.d, text, fnt, track), y1=bb[3]))

    def rect(self, box, col, a=1.0):
        if a > 0.004: self.d.rectangle(box, fill=col + (int(255 * a),))


def fade(t, t0, t1, fi=.25, fo=.25):
    return min(1, max(0, (t - t0) / fi)) * min(1, max(0, (t1 - t) / fo)) if fo > 0 else min(1, max(0, (t - t0) / fi))


_shade = {}


def shade(base, cx, cy, rx, ry, a):
    key = (cx, cy, rx, ry)
    if key not in _shade: _shade[key] = np.exp(-(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2))[..., None].astype(np.float32)
    return base * (1 - a * _shade[key])


def counter(final, t, t0, t1):
    """Number runs from 0 to its final value (t0→t1, ease-out); returns the string and whether it has settled"""
    v = int(final.replace(',', '')); u = min(1, max(0, (t - t0) / (t1 - t0))); u = 1 - (1 - u) ** 3
    s = f'{int(round(v * u)):,}'
    return s, u >= 1


def lock_digits(final, t, t0, step):
    digits = [i for i, c in enumerate(final) if c.isdigit()]
    k = int((t - t0) / step); s = list(final)
    r = np.random.default_rng(int(t * 1000))
    for j, i in enumerate(digits):
        if j >= k: s[i] = str(r.integers(0, 10))
    return ''.join(s), k >= len(digits)


def dial_hour(t):
    keys = [(4, 4.0), (6, 6.0), (8, 8.0), (16, 12.0), (20, 13.0), (24, 16.0), (32, 16.0), (34, 19.5), (35, 21.0), (40, 23.8), (42, 28.0)]
    for (a, ha), (b, hb) in zip(keys, keys[1:]):
        if a <= t < b: return ha + (hb - ha) * (t - a) / (b - a)
    return 4.0


def draw_dial(L, t):
    if not (bar(2) <= t < STOP): return
    a = fade(t, bar(2), STOP, .3, .05)
    frozen = BRAKE <= t < DUSK
    if frozen: a *= .45
    if FLASH <= t < STOP:     # flashback: reversed
        h = 23.8 - (23.8 - 4.0) * ((t - FLASH) / (STOP - FLASH)) ** .8
    else:
        h = dial_hour(t) % 24
    cx, cy, r = 1726, 948, 40
    d = L.d
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=DIM + (int(140 * a),), width=1)
    for k in range(24):
        ang = math.radians(k * 15 - 90); r0 = r - (6 if k % 6 == 0 else 3)
        d.line([cx + r0 * math.cos(ang), cy + r0 * math.sin(ang), cx + r * math.cos(ang), cy + r * math.sin(ang)], fill=DIM + (int(170 * a),), width=1)
    # the arc travelled (last 3 hours) + a sodium-orange dot
    a0 = h * 15 - 90
    d.arc([cx - r, cy - r, cx + r, cy + r], a0 - 45, a0, fill=SODIUM + (int(200 * a),), width=3)
    ang = math.radians(a0); px, py = cx + r * math.cos(ang), cy + r * math.sin(ang)
    d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=SODIUM + (int(255 * a),))
    fl = font(F_LAT, 11)
    for lab, k in (('00', 0), ('06', 6), ('12', 12), ('18', 18)):
        ang = math.radians(k * 15 - 90); rr = r + 14
        w = d.textlength(lab, font=fl)
        L.text(f'dial{lab}', cx + rr * math.cos(ang) - w / 2, cy + rr * math.sin(ang) - 7, lab, fl, DIM, 0, a * .9, final=a > .98)


def texts(t, f):
    """All on-screen text (left-aligned, no backing plate). Returns (Layer, list of darkening functions)"""
    L = Layer(); sh = []
    # 1 title (over the ISS photo)
    if t < bar(2):
        a1 = fade(t, .25, 3.9, .3, .3); a2 = fade(t, .5, 3.9, .3, .3)
        sh.append((520, 860, 760, 260, .55 * max(a1, a2)))
        L.text('title_cn', 168, 760, '纽约的一天', font(F_SC, 66, 300), INK, .14, a1)
        L.text('title_en', 172, 862, 'ONE DAY IN NEW YORK', font(F_LAT, 20), INK, .32, a2)
    # 2 population (noon cloud river)
    if NOON + .2 <= t < GRID:
        t0 = NOON + .2
        num, ok = lock_digits('8,804,190', t, t0 + .1, BEAT / 4)
        a = fade(t, t0, GRID, .12, .05)
        sh.append((560, 820, 780, 270, .58 * a))
        L.text('pop_num', 168, 690, num, font(F_LAT, 84), INK, .06, a, final=ok)
        w = min(1, max(0, (t - t0 - .2) / .9))
        L.rect([172, 806, 172 + int(560 * w), 808], SODIUM, a)
        L.text('pop_cn', 172, 826, '纽约市人口 · 2020 普查', font(F_SC, 28, 350), INK, .12, a)
        L.text('pop_en', 172, 874, 'NEW YORK CITY · 2020 CENSUS', font(F_LAT, 16), DIM, .25, a)
    # 3 split screen: the Brooklyn Bridge in 1899 / today
    if bar(13, 2) <= t < bar(15, 2):
        t0 = bar(13, 2); a = fade(t, t0 + .05, bar(15, 2), .2, .06)
        L.text('y1899', 64, 968, '1899', font(F_LAT, 22), INK, .3, fade(t, t0, bar(15, 2), .12, .06))
        sh.append((1290, 860, 520, 300, .62 * a))
        x0 = 1012
        L.text('bb_cn', x0, 640, '布鲁克林大桥，每天', font(F_SC, 28, 350), INK, .12, a)
        L.text('bb_en', x0 + 2, 686, 'BROOKLYN BRIDGE · EACH DAY, 2024', font(F_LAT, 14), DIM, .25, a)
        L.rect([x0 + 2, 718, x0 + 2 + int(430 * min(1, max(0, (t - t0 - .2) / .6))), 719], SODIUM, a)
        rows = [('103,051', '机动车', 'VEHICLES'), ('28,845', '行人', 'PEDESTRIANS'), ('5,504', '自行车', 'CYCLISTS')]
        for k, (v, cn, en) in enumerate(rows):
            tk = t0 + .25 + k * BEAT / 3
            s, ok = counter(v, t, tk, tk + .55)
            ak = a * fade(t, tk, bar(15, 2), .15, .06)
            y = 740 + k * 78
            L.text(f'bb_n{k}', x0, y, s, font(F_LAT, 44), INK, .05, ak, final=ok)
            L.text(f'bb_c{k}', x0 + 300, y + 4, cn, font(F_SC, 24, 350), INK, .1, ak)
            L.text(f'bb_e{k}', x0 + 300, y + 38, en, font(F_LAT, 12), DIM, .25, ak)
    # 4 Times Square crowds
    if bar(18) + .1 <= t < FLASH:
        t0 = bar(18) + .1; a = fade(t, t0, FLASH, .15, .05)
        sh.append((560, 820, 780, 270, .6 * a))
        s, ok = counter('220,000', t, t0 + .05, t0 + .7)
        L.text('ts_num', 168, 690, '≈' + s, font(F_LAT, 84), INK, .06, a, final=ok)
        L.rect([172, 806, 172 + int(560 * min(1, max(0, (t - t0 - .2) / .7))), 808], SODIUM, a)
        L.text('ts_cn', 172, 826, '每天走进时报广场（2024）', font(F_SC, 28, 350), INK, .12, a)
        L.text('ts_en', 172, 874, 'PEOPLE A DAY · TIMES SQUARE · 2024', font(F_LAT, 16), DIM, .25, a)
    draw_dial(L, t)
    # 5 quotation (over the time-lapse of the next day's dawn)
    if CARD <= t < SLATE:
        u = t - CARD; out = min(1, max(0, (SLATE - .03 - t) / .15))
        fd = lambda t0: min(1, max(0, (u - t0) / .12)) * out
        sh.append((560, 860, 820, 300, .62 * out))
        x0, y0 = 196, 724
        L.text('q_cn', x0, y0, '我也曾在人群里。', font(F_SC, 60, 300), INK, .1, fd(0))
        L.text('q_en', x0 + 4, y0 + 104, '…I WAS ONE OF A CROWD,', font(F_LAT, 20), INK, .16, fd(.08))
        L.text('q_src', x0 + 4, y0 + 152, 'WALT WHITMAN, LEAVES OF GRASS, 1860', font(F_LAT, 14), SODIUM, .22, fd(.12))
    # 6 end slate (the darkened dawn shot keeps running). The small credit text is written in full but not reported to readcheck (end credit line, see DEMO.md)
    if t >= SLATE:
        u = t - SLATE; out = min(1, max(0, (DUR - .02 - t) / .15))
        fd = lambda t0: min(1, max(0, (u - t0) / .15)) * out
        x0 = 196
        L.text('s_title_cn', x0, 250, '纽约的一天', font(F_SC, 54, 300), INK, .14, fd(0))
        L.text('s_title_en', x0 + 330, 276, 'ONE DAY IN NEW YORK', font(F_LAT, 20), INK, .3, fd(0))
        L.rect([x0 + 2, 350, x0 + 2 + int(640 * ease(u / .5)), 351], SODIUM, out)
        L.text('s_style_cn', x0, 376, '延时交响', font(F_SC, 26, 350), INK, .14, fd(.05))
        L.text('s_style_en', x0 + 132, 384, 'TIME-LAPSE SYMPHONY', font(F_LAT, 15), DIM, .3, fd(.05))
        L.text('s_lemo', x0, 432, 'LemoLab × Claude Opus 5.5', font(F_SC, 24, 400), INK, .04, fd(.1))
        fc = font(F_SC, 16, 380); y = 530
        for k, line in enumerate(CREDIT_LINES):
            L.text(f's_cr{k}', x0, y + k * 29, line, fc, (196, 190, 180), .01, fd(.1), final=False)
    return L, sh


CREDIT_LINES = [
    'Footage under CC BY 3.0 (creativecommons.org/licenses/by/3.0) or CC BY 2.0 (creativecommons.org/licenses/by/2.0), cut, retimed, cropped and colour-graded:',
    'Scott Herder, “New York in Motion” (2018), CC BY 3.0 · David Schwab, “Time-lapse of New York City skyline July 2023”, CC BY 3.0',
    'Longfellow Films, “Empty New York city” (2020), CC BY 3.0 · Joe Cavallini, “DIS:CONNECTED – NYC DURING COVID-19” (2020), CC BY 3.0',
    '350.org, “Aerial Footage – People\'s Climate March” (2014), CC BY 3.0 · Branded Cities, “Earth Hour Set At Times Square” (2019), CC BY 3.0',
    'Steven Kelley, “42nd Time Lapse” (2012), CC BY 2.0 · Jason Eppink, “steel beams | N over the Manhattan Bridge” (2012), CC BY 2.0',
    'Sunny Ripert, “5 seconds of Times Square” (2010), CC BY 2.0',
    'Public domain: Library of Congress (Highsmith; Edison 1899) · NASA ISS047 (Tim Kopra) · U.S. Marine Corps / DVIDS (Fleet Week 2016) · Internet Archive (Whitman 1860)',
]


# ───────── compositing ─────────
class State:
    def __init__(self): self.cur = None; self.rd = {}; self.gains = {}; self.fx = None; self.mem = {}

    def reader(self, cid, skip=0):
        if cid not in self.rd: self.rd[cid] = Reader(cid, skip)
        return self.rd[cid]

    def close_all(self):
        for r in self.rd.values(): r.close()
        self.rd = {}


ST = State()
GUT = 6   # grid / split-screen gutter


def gain(key, frame, strength):
    if key not in ST.gains: ST.gains[key] = wb_gains(frame, strength)
    return ST.gains[key]


def pool_frames(cid):
    if cid not in ST.mem:
        fr = load_clip(cid, (960, 540)); g = wb_gains(fr[len(fr) // 2], .35 if CLIPS[cid]['src'] != 'sky' else .2)
        ST.mem[cid] = [(a.astype(np.float32) * g).clip(0, 255).astype(np.uint8) for a in fr]
    return ST.mem[cid]


ORDER9 = [4, 0, 8, 2, 6, 1, 7, 3, 5]
ORDER16 = [5, 10, 0, 15, 3, 12, 6, 9, 1, 14, 4, 11, 2, 13, 7, 8]


def grid_plate(t, f, stage=None):
    if stage is None: stage = max(k for k, s in enumerate(GRID_STAGES) if t >= s[0] - 1e-9)
    t0, cols, rows, ids = GRID_STAGES[stage]
    n = cols * rows
    step = min(BEAT / 4, .3 / n)
    filling = stage > 0 and cols * rows > 2 and t < t0 + n * step
    # during the frames when the next grid level lights up, cells not yet lit keep the previous level's picture (no flash to black)
    out = grid_plate(t, f, stage - 1) if filling else np.zeros((H, W, 3), np.float32)
    if cols == 2 and rows == 1:          # 1×2: full-resolution centre crop
        for k, cid in enumerate(ids):
            key = 'full_' + cid
            if key not in ST.mem:
                fr = load_clip(cid); g = wb_gains(fr[len(fr) // 2], .35)
                ST.mem[key] = [(a.astype(np.float32) * g).clip(0, 255).astype(np.uint8) for a in fr]
            fr = ST.mem[key]; i = min(len(fr) - 1, max(0, f - round(t0 * FPS)))
            x0 = k * (W // 2)
            on = t >= t0 + k * BEAT / 2
            if on: out[:, x0:x0 + W // 2] = fr[i][:, 480:1440]
        out[:, W // 2 - GUT // 2:W // 2 + GUT // 2] = 0
        return out
    cw, ch = W // cols, H // rows
    order = ORDER9 if n == 9 else ORDER16 if n == 16 else list(range(n))
    frantic = stage == len(GRID_STAGES) - 1 and t >= GRID_STAGES[-1][0] + BEAT   # last beat: change every sixteenth
    shift = int((t - (GRID_STAGES[-1][0] + BEAT)) / (BEAT / 4)) + 1 if frantic else 0
    for k in range(n):
        lit = t >= t0 + order.index(k) * step
        if not lit: continue
        cid = ids[(k + shift * 5) % len(ids)]
        fr = pool_frames(cid); i = min(len(fr) - 1, max(0, f - round(t0 * FPS)))
        cell = np.asarray(Image.fromarray(fr[i]).resize((cw, ch), Image.BILINEAR)) if (cw, ch) != (960, 540) else fr[i]
        cx, cy = (k % cols) * cw, (k // cols) * ch
        out[cy:cy + ch, cx:cx + cw] = cell
    for c in range(1, cols): out[:, c * cw - GUT // 2:c * cw + GUT // 2] = 0
    for r in range(1, rows): out[r * ch - GUT // 2:r * ch + GUT // 2, :] = 0
    return out


def split_plate(s, t, f, i):
    out = np.zeros((H, W, 3), np.float32)
    if i == 0:
        ST.close_all()
    l = ST.reader(s['left']).next(); r = ST.reader(s['right']).next()
    gl = gain('L' + s['left'], l, 0); gr = gain('R' + s['right'], r, .4)
    # left: the 1899 film (1440×1080, 4:3), take the middle 960 px width; right: today, take the middle 960 px width
    out[:, :W // 2] = l[:, 240:1200].astype(np.float32) * gl
    out[:, W // 2:] = r[:, 480:1440].astype(np.float32) * gr
    # opening: the centre seam grows up and down from the middle (0.25 s)
    g = ease(i / 8)
    out[:, W // 2 - GUT // 2:W // 2 + GUT // 2] = 0
    if g < 1:
        hh = int(H / 2 * g)
        out[:H // 2 - hh, :W // 2] *= .0; out[H // 2 + hh:, :W // 2] *= .0
    return out


def plate_for(s, t, f, i, n):
    """Return the white-balanced picture (float32) and the bloom strength"""
    kind = s['kind']
    if kind == 'clip':
        if i == 0: ST.close_all(); ST.fx = None
        raw = ST.reader(s['id'], skip=(i if i > 0 and s['id'] not in ST.rd else 0)).next()
        mv = s['motion']; u = ease(i / max(1, n - 1)); sc = mv[0] + (mv[1] - mv[0]) * u
        raw = move(raw, sc, mv[2] * u, mv[3] * u, f)
        p = raw.astype(np.float32) * gain(s['id'], raw, s['wb'])
        if s.get('fx') == 'trails':
            if ST.fx is None: ST.fx = Trails(s['id'])
            p = ST.fx(p, i, n)
        if s['id'] == 's36_dawn' and t >= SLATE:
            p = p * (1 - .78 * ease((t - SLATE) / .35))
        night = s['src'] in NIGHT_SRC or s['id'] in ('s02_sky_dawn', 's25_sky_dusk')
        return p, (.17 if night else .09)
    if kind == 'photo':
        names = s['names']; nm = names[(i // 2) % len(names)]
        u = ease(i / max(1, n - 1))
        sc = orbit_scale(t - s['t0']) if s['id'] == 's01_orbit' else s['s'][0] + (s['s'][1] - s['s'][0]) * u
        if s['id'] == 's01_orbit' and t < .5:          # 360° shutter during the slam-in: average 6 zoom levels within one frame = radial motion blur
            raw = np.mean([photo_frame(nm, s['c'], orbit_scale(t + k / FPS / 6)).astype(np.float32) for k in range(6)], 0).astype(np.uint8)
        else:
            raw = photo_frame(nm, s['c'], sc)
        raw = move(raw, 1.0, s['drift'][0] * u, s['drift'][1] * u, f)
        p = raw.astype(np.float32) * gain(s['id'] + nm, raw, s['wb']) * s.get('expo', 1.0)
        if s['id'] == 's01_orbit':
            p *= min(1, (t + 1 / FPS) / .1)                 # slams out of black in 3 frames
        return p, (.2 if s['id'] in ('s01_orbit', 's27_ph_ts') else .09)
    if kind == 'flicker':
        if i == 0: ST.close_all()
        a = ST.reader(s['a']).next(); b = ST.reader(s['b']).next()
        return (a if (i // 2) % 2 == 0 else b).astype(np.float32), .14
    if kind == 'grid':
        if i == 0: ST.close_all()
        return grid_plate(t, f), .08
    if kind == 'split':
        return split_plate(s, t, f, i), .07
    if kind == 'page':
        p = page_frame(i, n) * min(1, i / (.35 * FPS)); return p, .05
    return np.zeros((H, W, 3), np.float32), 0


def main():
    stills = []
    if '--still' in sys.argv:
        a = sys.argv[sys.argv.index('--still') + 1:]
        stills = [(float(a[k]), a[k + 1]) for k in range(0, len(a) - 1, 2)]
        frames = sorted(round(t * FPS) for t, _ in stills)
        outp = None
    else:
        outp = sys.argv[1]; frames = range(NF)
    ranges = [(round(s['t0'] * FPS), round(s['t1'] * FPS), s) for s in SHOTS]
    f_flash0, f_stop = round(FLASH * FPS), round(STOP * FPS)
    plan = []; occ = {}
    for sid, ln in zip(FLASH_SRC, FLASH_LEN):
        occ[sid] = occ.get(sid, 0) + 1; plan.append((sid, ln, 'mid' if occ[sid] == 1 else 'end'))
    cache = {}
    enc = None
    if outp:
        enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                '-c:v', 'libx264', '-crf', '14', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709',
                                '-color_trc', 'bt709', '-colorspace', 'bt709', outp], stdin=subprocess.PIPE)
    rec = {}          # readcheck: id → [text, box, start frame, end frame]
    spans = []
    cur_id = None; fl_i = fl_k = 0
    still_map = {round(t * FPS): p for t, p in stills}
    for f in frames:
        t = f / FPS
        hit = next((r for r in ranges if r[0] <= f < r[1]), None)
        bloom = .08
        if hit is None:
            img = np.zeros((H, W, 3), np.float32)
        else:
            a, b, s = hit; i = f - a; n = b - a
            if s['kind'] == 'flash':
                if outp is None:
                    img = np.zeros((H, W, 3), np.float32)
                else:
                    sid, ln, which = plan[fl_i]
                    lst = cache.get((sid, which)) or cache.get((sid, 'mid'))
                    img = lst[fl_k % len(lst)].astype(np.float32); fl_k += 1
                    if fl_k >= ln: fl_i += 1; fl_k = 0
                    bloom = .12
            else:
                if outp is None and s['kind'] in ('clip', 'split', 'flicker'):
                    ST.close_all()
                    if s['kind'] == 'clip':
                        ST.rd[s['id']] = Reader(s['id'], skip=i)
                        if s.get('fx') == 'trails':      # when grabbing a still, run the light-trail state up to that frame
                            ST.fx = Trails(s['id']); r2 = Reader(s['id'])
                            for j in range(i):
                                fr = r2.next(); ST.fx(fr.astype(np.float32), j, n)
                            r2.close()
                    elif s['kind'] == 'split':
                        ST.rd[s['left']] = Reader(s['left'], skip=i); ST.rd[s['right']] = Reader(s['right'], skip=i)
                    else:
                        ST.rd[s['a']] = Reader(s['a'], skip=i); ST.rd[s['b']] = Reader(s['b'], skip=i)
                    img, bloom = plate_for(s, t, f, i, n)
                else:
                    img, bloom = plate_for(s, t, f, i, n)
                if outp and s['id'] in FLASH_SRC:
                    if n // 2 - 2 <= i < n // 2 + 2: cache.setdefault((s['id'], 'mid'), []).append(img.clip(0, 255).astype(np.uint8))
                    if i >= n - 4: cache.setdefault((s['id'], 'end'), []).append(img.clip(0, 255).astype(np.uint8))
        L, sh = texts(t, f)
        for cx, cy, rx, ry, a in sh: img = shade(img, cx, cy, rx, ry, a)
        out = grade(img, bloom) if hit is not None and np.any(img) else img
        bb = L.im.getbbox()                          # composite only inside the rectangle that has text
        if bb:
            x0, y0, x1, y1 = bb
            lay = np.asarray(L.im.crop(bb)).astype(np.float32); al = lay[..., 3:4] / 255
            out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - al) + lay[..., :3] * al
        fr = finish(out, f)
        if outp is None:
            Image.fromarray(fr).save(still_map[f], quality=92); print(still_map[f], flush=True); continue
        enc.stdin.write(fr.tobytes())
        for r in L.rec:
            k = r['id']; box = [round(r['x0']), round(r['y0']), round(r['x1']), round(r['y1'])]
            if k in rec and rec[k][0] == r['text'] and rec[k][3] == f - 1:
                rec[k][3] = f
            else:
                if k in rec: spans.append(dict(id=k, text=rec[k][0], box=rec[k][1], f0=rec[k][2], f1=rec[k][3]))
                rec[k] = [r['text'], box, f, f]
        if f % 60 == 0: print(f'{t:5.1f}s', flush=True)
    if outp:
        for k, v in rec.items(): spans.append(dict(id=k, text=v[0], box=v[1], f0=v[2], f1=v[3]))
        enc.stdin.close(); enc.wait()
        json.dump(dict(fps=FPS, dur=DUR, spans=spans), open('texts.json', 'w'), ensure_ascii=False)
        print(outp, len(spans), 'text spans')
    ST.close_all()


if __name__ == '__main__':
    main()

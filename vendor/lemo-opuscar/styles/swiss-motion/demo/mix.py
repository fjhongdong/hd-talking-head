"""Mix: score (music/score.wav) + voice-over (voices/*.wav) + procedural foley (metal type, paper, utility knife, steel ruler) → mix.wav
python styles/swiss-motion/demo/mix.py   (run events.mjs first to generate events.json)
Foley follows the material: metal type = short metallic transient + 3–5 kHz resonance; paper = low-passed noise + paper-surface friction; utility knife = band-pass sweep + metallic snick; all dry, no reverb."""
import sys, os, json, numpy as np, soundfile as sf
from scipy.signal import resample_poly
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '../../../core/audio'))
import sfx
from sfx import SR, t_, env_exp, bp, lp, hp, noise, norm, add

rng = np.random.default_rng(26)
ev = json.load(open(os.path.join(HERE, 'events.json')))
DUR = ev['dur'] + .5
N = int(DUR * SR)

# ---------------- foley ----------------
def type_clack(v=1.0, big=False):
    """Metal type dropping into the composing tray: metallic transient + two high-frequency resonances + low end of the wooden tray"""
    d = .12 if big else .07; tt = t_(d); p = .92 + rng.random() * .16
    x = hp(noise(d), 2500) * env_exp(d, .0012) * .9
    x += sum(a * np.sin(2 * np.pi * f * p * tt + rng.random() * 6) * env_exp(d, tau) for f, a, tau in [(3300, .45, .010), (5100, .25, .006), (1250, .35, .016)])
    x += np.sin(2 * np.pi * (140 if big else 420) * p * tt) * env_exp(d, .03 if big else .012) * (.9 if big else .35)
    return norm(x) * v

def rule_line(v=1.0):
    """Steel-ruler line: a very short, very light "hiss" """
    d = .05; return norm(bp(noise(d), 3000, 9000) * np.sin(np.pi * t_(d) / d) ** 2) * v

def knife(d=.45, v=1.0):
    """Utility knife: the blade sliding across (rising band-pass sweep) + a metallic snick at the end"""
    n = noise(d); tt = t_(d); out = np.zeros_like(n); hop = 240
    for i in range(0, len(n), hop):
        f = 1500 + 4500 * (i / len(n)) ** 1.5
        seg = bp(n[max(0, i - 1200):i + hop], f * .8, min(f * 1.25, 20000))[-hop:]; out[i:i + len(seg)] = seg
    out *= np.minimum(1, tt / (d * .7)) ** 1.5 * np.exp(-np.maximum(0, tt - d * .8) / .02)
    sn = t_(.08); snick = np.sin(2 * np.pi * 4200 * sn) * env_exp(.08, .012) + hp(noise(.08), 4000) * env_exp(.08, .003)
    x = np.concatenate([out * .7, np.zeros(int(.0 * SR))]); x[-len(sn):] += snick[:len(sn)] * .8
    return norm(x) * v

def paper(v=1.0):
    """Paper laid down: low end of the air being pushed out + a slap of the paper surface"""
    d = .25; tt = t_(d)
    x = lp(noise(d), 900) * env_exp(d, .03) + np.sin(2 * np.pi * 110 * tt) * env_exp(d, .04) * .6 + hp(noise(d), 3000) * env_exp(d, .006) * .4
    return norm(x) * v

def thunk(v=1.0):
    """The giant numeral rising step by step: a deep wooden "thud" """
    d = .12; tt = t_(d)
    return norm(np.sin(2 * np.pi * 95 * tt) * env_exp(d, .025) + bp(noise(d), 300, 1500) * env_exp(d, .006) * .6) * v

def slide(v=1.0, d=.2):
    """Paper sliding"""
    tt = t_(d); return norm(bp(noise(d), 700, 5000) * np.sin(np.pi * tt / d) ** 1.5) * v

def snap(v=1.0):
    """Bar block snapping in: a small wooden click"""
    d = .05; tt = t_(d)
    return norm(hp(noise(d), 1500) * env_exp(d, .002) + np.sin(2 * np.pi * 1900 * tt) * env_exp(d, .007) * .6 + np.sin(2 * np.pi * 620 * tt) * env_exp(d, .01) * .4) * v

def thump(v=1.0):
    """Red circle landing: dull, round"""
    d = .45; tt = t_(d)
    return norm(np.sin(2 * np.pi * 58 * tt * (1 - .25 * tt)) * env_exp(d, .09) + lp(noise(d), 250) * env_exp(d, .02) * .4) * v

def tick(v=1.0):
    d = .03; tt = t_(d); return norm(np.sin(2 * np.pi * 3600 * tt) * env_exp(d, .004) + hp(noise(d), 5000) * env_exp(d, .001) * .5) * v

FOLEY = {
    'clack': (lambda e: type_clack(), .16), 'clackBig': (lambda e: type_clack(big=True), .30),
    'rule': (lambda e: rule_line(), .07), 'knife': (lambda e: knife(.45 if e['t'] in (0, 39.0) else .16), .22),
    'paper': (lambda e: paper(), .30), 'thunk': (lambda e: thunk(), .22), 'slide': (lambda e: slide(), .10),
    'snap': (lambda e: snap(), .12), 'thump': (lambda e: thump(), .45), 'tick': (lambda e: tick(), .10),
    'swish': (lambda e: sfx.whoosh(e.get('d', .5)), .10),
}
fol = np.zeros((N, 2))
for e in ev['ev']:
    if e['type'] not in FOLEY: continue
    fn, gain = FOLEY[e['type']]; x = fn(e).astype(np.float64)
    at = e['t']
    if e['type'] == 'knife' and e['t'] not in (0, 39.0): at -= len(x) / SR - .02      # short cut: the snick lands on the beat
    add(fol, x, at, gain * e.get('g', 1), pan=float(rng.uniform(-.25, .25)))

# ---------------- voice-over ----------------
lines = json.load(open(os.path.join(HERE, 'lines.json')))
vo = np.zeros((N, 2)); vad = np.zeros(N)
for L in lines:
    y, sr = sf.read(os.path.join(HERE, 'voices', L['id'] + '.wav'))
    if y.ndim > 1: y = y.mean(1)
    y = resample_poly(y, SR, sr); y = hp(y, 90); y = sfx.compress(y / (np.abs(y).max() + 1e-9), thr=.3, ratio=3, att=.003, rel=.1)
    y = norm(y, .9)
    add(vo, y, L['t'], .72)
    s = int(L['t'] * SR); vad[s:s + len(y)] = 1
# ducking envelope: duck 80 ms early, release 250 ms
from scipy.ndimage import maximum_filter1d, uniform_filter1d
vad = maximum_filter1d(vad, size=int(.16 * SR)); vad = uniform_filter1d(vad, size=int(.25 * SR))
duck = 1 - .68 * vad   # ≈ −10 dB

# ---------------- score ----------------
mus, msr = sf.read(os.path.join(HERE, 'music', 'score.wav'))
assert msr == SR, msr
mus = mus[:N] if len(mus) >= N else np.pad(mus, ((0, N - len(mus)), (0, 0)))
mus = mus * duck[:, None] * .80

mix = mus + vo + fol
for c in range(2): mix[:, c] = sfx.limit(mix[:, c], .95)
assert np.isfinite(mix).all()
sf.write(os.path.join(HERE, 'mix.wav'), mix.astype(np.float32), SR, subtype='FLOAT')

# level meter: RMS per section (dBFS)
def db(x): return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
print('peak %.2f dBFS' % (20 * np.log10(np.abs(mix).max())))
for L in lines:
    s = int(L['t'] * SR); e = s + int(sf.info(os.path.join(HERE, 'voices', L['id'] + '.wav')).duration * SR)
    print(f"{L['id']:4s} voice {db(vo[s:e]):6.1f}  music {db(mus[s:e]):6.1f}  foley {db(fol[s:e]):6.1f}")
for a, b in [(0, 4), (4, 16), (16, 24), (24, 26), (26, 30), (30, 32), (32, 36), (36, 40), (40, 44)]:
    s, e = int(a * SR), int(b * SR); print(f'{a:>2}-{b:<2} mix {db(mix[s:e]):6.1f}  music {db(mus[s:e]):6.1f}  foley {db(fol[s:e]):6.1f}')

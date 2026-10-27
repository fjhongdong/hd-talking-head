#!/usr/bin/env python3
"""Score + foley + narration + ambience -> out/mix.wav (and stems in audio/stems/).
    $LIB/.venv/bin/python <demo>/audio/mix.py

Score: an original "machine" score in D minor, 120 BPM (1 beat = 0.5 s, 1 bar = 2 s), sampled instruments
(core/audio/sampler.py; VSCO 2 CE, VCSL and FreePats, all CC0): spiccato cellos + staccato bassoon ostinato,
staccato tuba/trombone on the beat, horns and trumpets for stabs and the motif, snare, gran cassa, timpani,
xylophone, gong. Real recordings where we have them (rivet gun, steam whistle, construction site), procedural
foley (core/audio/sfx.py) for paper, marker, slams. Every time comes from events.json (exported from the page).
"""
import sys, json, subprocess
from pathlib import Path
import numpy as np, soundfile as sf

HERE = Path(__file__).resolve().parent.parent          # demo/
LIB = Path(__import__('os').environ.get('LIB', HERE.parent.parent.parent)).resolve()
sys.path.insert(0, str(LIB))
from core.audio import sampler as S
from core.audio import sfx as X
from core.audio.sfx import SR, add

S.seed(1930)
EVJ = json.load(open(HERE / "events.json"))
DUR, EV = EVJ["dur"], EVJ["ev"]
N = int((DUR + .5) * SR)
B = .5
SIL = (48.25, 48.75)                     # the true silence before the result
QUIET = (28.0, 31.5)                     # the orchestra stops: only the rivet gun and the site
evt = lambda ty: [e for e in EV if e["type"] == ty]
first = lambda ty: evt(ty)[0]["t"]


def load(name):
    c = sorted((HERE / "raw").glob(name + ".*"))
    if not c: return None
    out = HERE / "out" / f"{name}.wav"; out.parent.mkdir(exist_ok=True)
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(c[0]), "-ac", "1", "-ar", str(SR), str(out)], check=True)
    return sf.read(out, dtype="float32")[0]


def cut(x, a, b, fade=.008):
    y = x[int(a * SR):int(b * SR)].copy(); n = int(fade * SR)
    y[:n] *= np.linspace(0, 1, n); y[-n:] *= np.linspace(1, 0, n); return y


def gate(buf, a, b, f=.008):
    i0, i1, n = int(a * SR), int(b * SR), int(f * SR)
    buf[i0 - n:i0] *= np.linspace(1, 0, n)[:, None]; buf[i0:i1] = 0


# ============================================================ score
ev = []
def E(*a): ev.append(a)
m = S.midi
CELL = ['D3', 'D3', 'F3', 'D3', 'A2', 'D3', 'E3', 'F3']          # the machine figure, eighths
def ostinato(t0, t1, tr=0, vel=.6, bassoon=True, oct_=0):
    n = int(round((t1 - t0) / .25))
    for i in range(n):
        p = m(CELL[i % 8]) + tr + 12 * oct_
        E(t0 + i * .25, 'cellos_spic', p, .22, vel + .1 * (i % 4 == 0), -.2)
        if bassoon and i % 2 == 0: E(t0 + i * .25, 'bassoon_stac', p + 12, .2, vel * .8, .25)
def beats(t0, t1, tr=0, vel=.68):
    for k in range(int(round((t1 - t0) / B))):
        t = t0 + k * B
        E(t, 'tuba_stac' if k % 2 == 0 else 'trombone_stac', m('D2') + tr + (-5 if k % 4 == 2 else 0), .3, vel, .1)
def snare(t0, t1, vel=.32):
    for i in range(int(round((t1 - t0) / .125))):
        E(t0 + i * .125, 'snare2', 'taps' if i % 4 else 'on', None, vel + .2 * (i % 8 == 4), .25)
MOTIF = [('D5', .25), ('D5', .25), ('F5', .5), ('E5', .25), ('D5', .25), ('A4', .5)]
def motif(t0, tr=0, inst='trumpet_stac', vel=.68):
    t = t0
    for p, d in MOTIF: E(t, inst, m(p) + tr, d * .8, vel, .3); t += d
def stab(t, ps, vel=.8, inst='horn_stac', d=.3):
    for p in ps: E(t, inst, p, d, vel, -.15)

# 0–5 title: the strike, 4-1-0 stamps, the machine starts
E(0, 'gran_cassa', None, None, .95, 0); E(0, 'timpani', 'D2', 1.4, .9, 0); E(0, 'tuba', 'D1', 1.2, .8, 0); E(0, 'trombone', 'D2', .9, .8, .1)
for t, p in ((.5, 'D2'), (.625, 'F2'), (.75, 'A2')): E(t, 'trombone_stac', p, .14, .78, .15)
stab(.875, [m('D4'), m('F4'), m('A4')], .9); E(.875, 'timpani', 'A2', .5, .8, 0)
ostinato(1.0, 4.75); beats(2.0, 4.75); snare(3.0, 4.75, .26)
for k in range(4): E(1.0 + k * 1.0, 'xylophone', 'D6' if k % 2 else 'A5', .2, .5, .45)
# 5–8.75 the site: half the band, the voice on top
ostinato(5.0, 8.25, vel=.48, bassoon=False)
for k in range(6): E(5.0 + k * .5, 'contrabass_pizz', 'D1' if k % 2 == 0 else 'A1', .4, .55, 0)
for i in range(8): E(7.75 + i * .0625, 'timpani', 'A2', .1, .25 + .06 * i, 0)          # roll into the iris
# 8.75–11.5 first steel
E(8.75, 'gran_cassa', None, None, .8, 0); E(8.75, 'tuba_stac', 'D1', .4, .85, 0); E(9.125, 'trombone_stac', 'D2', .3, .8, 0)
ostinato(9.0, 11.5, vel=.55); beats(9.5, 11.5, vel=.6)
# 11.5–16 the grid and the strips: the full machine; one xylophone note per lit cell, rising
ostinato(11.5, 16.0, vel=.62); beats(11.5, 16.0); snare(11.5, 16.0)
for k, p in enumerate(['D5', 'E5', 'F5', 'G5', 'A5', 'Bb5', 'C6', 'D6']): E(11.5 + k * .25, 'xylophone', p, .2, .62, .4)
stab(13.5, [m('D4'), m('A4'), m('D5')], .9); E(13.5, 'timpani', 'D3', .6, .85, 0)
motif(14.5); motif(15.5, -2)
# 16–18.5 freeze: the band stops on one held chord; a timpani note on the jump-in
for p in ('D3', 'F3', 'A3', 'D4'): E(16.0, 'horn', p, 2.2, .55, -.1)
for p in ('D2', 'A2'): E(16.0, 'trombone', p, 2.2, .5, .1)
E(16.0, 'contrabass', 'D1', 2.4, .5, 0); E(16.0, 'sus_cymbal', None, None, .35, 0); E(17.25, 'timpani', 'A2', .5, .6, 0)
for i in range(12): E(17.5 + i * .0625, 'snare', 'on', None, .12 + .04 * i, .2)
# 18.5–23.25 the brochure: two horn stabs, ostinato an octave up and lighter
stab(18.5, [m('D4'), m('F4'), m('A4')], .85); stab(18.75, [m('D4'), m('F4'), m('A4')], .9)
E(18.5, 'timpani', 'D3', .6, .8, 0)
ostinato(19.0, 23.25, vel=.5, oct_=1, bassoon=False); beats(19.0, 23.25, vel=.55)
# 23.25–28 eighty hours: up a fourth, trumpet motif, timpani roll, then everything stops at 27.75
ostinato(23.25, 27.75, tr=5, vel=.56); beats(23.25, 27.75, tr=5); snare(25.25, 27.75, .3)
motif(23.75, 5); motif(24.75, 5, 'horn_stac', .72); motif(25.75, 7)
for i in range(int(1.25 / .0625)): E(26.5 + i * .0625, 'timpani', 'A2', .1, .3 + .5 * i / 20, 0)
# 28 the question: one boom, then nothing but the site and the rivet gun (QUIET)
E(28.0, 'gran_cassa', None, None, .85, 0); E(28.0, 'tuba', 'D1', 1.4, .7, 0)
E(29.0, 'timpani', 'D2', 1.0, .9, 0)
# 31.5–35.5 the answer: strings come back, held, swelling
for inst, ps, v in (('violins', ('A4', 'D5', 'F5'), .5), ('violas', ('D4', 'A4'), .5), ('cellos', ('D3', 'A3'), .55), ('contrabass', ('D2',), .5)):
    for p in ps: E(31.5, inst, p, 4.0, v, 0)
stab(31.5, [m('D3'), m('A3'), m('D4')], .85, 'trombone_stac')
for k in range(8): E(31.5 + k * .5, 'gran_cassa', None, None, .35, 0)
# 35.5–40 the chart: pizzicato ticks; one brass chord per building, Dm -> F -> A -> D major
for i in range(int((40.0 - 35.5) / .25)): E(35.5 + i * .25, 'violins_pizz', 'D5' if i % 4 == 0 else 'A4', .2, .4, .3)
for t, ch in ((36.25, ('D3', 'F3', 'A3')), (36.625, ('F3', 'A3', 'C4')), (37.0, ('E3', 'A3', 'C#4')), (37.375, ('D3', 'F#3', 'A3', 'D4'))):
    for p in ch: E(t, 'horn', p, (40.0 - t) if t == 37.375 else .34, .62 if t < 37.3 else .7, -.1)
    E(t, 'timpani', ch[0][0] + '2' if ch[0][0] != 'C' else 'C3', .4, .7, 0)
for p in ('D2', 'A2', 'D3'): E(37.375, 'trombone', p, 2.6, .55, .1)
# 40 verdict: tutti stab in D major, then the machine rebuilds toward the tower
for inst, ps in (('trumpet_stac', ('D5', 'F#5', 'A5')), ('horn_stac', ('D4', 'F#4', 'A4')), ('trombone_stac', ('D3', 'A3')), ('tuba_stac', ('D2',))):
    for p in ps: E(40.0, inst, p, .4, .95, 0)
E(40.0, 'clash', None, None, .7, 0); E(40.0, 'timpani', 'D2', .8, 1.0, 0)
ostinato(40.5, 43.25, vel=.55); beats(41.0, 43.25, vel=.58); snare(42.0, 43.25, .28)
# 43.25–48.25 the tower: one rising note per floor, chords stepping up every bar, snare roll
SCALE = ['D4', 'E4', 'F4', 'G4', 'A4', 'Bb4', 'C5', 'D5', 'E5', 'F5', 'G5', 'A5', 'Bb5', 'C6', 'D6', 'E6']
for i, f in enumerate(evt('floor')):
    E(f['t'], 'xylophone', SCALE[i], .2, .6, .4); E(f['t'], 'violins_spic', m(SCALE[i]) - 12, .2, .55, .3)
for k, (t, root) in enumerate(((43.5, 'D'), (44.5, 'E'), (45.5, 'F'), (46.5, 'G'))):
    for p in (root + '2', root + '3'): E(t, 'trombone', p, .95, .55 + .08 * k, .1)
    ostinato(t, t + 1.0, tr=[0, 2, 3, 5][k], vel=.55 + .05 * k)
for i in range(int((48.25 - 46.5) / .0625)): E(46.5 + i * .0625, 'snare', 'on', None, .15 + .5 * i / 28, .2)
for p in ('D4', 'F#4', 'A4', 'D5'): E(47.65, 'trumpet', p, .7, .8, .2)
for p in ('D3', 'A3', 'D4'): E(47.65, 'horn', p, .7, .8, -.2)
# 48.75 the result: the heaviest hit, D major, long decay under the last two lines
E(48.75, 'gran_cassa', None, None, 1.0, 0); E(48.75, 'gong', None, None, .75, 0); E(48.75, 'timpani', 'D2', 3.0, 1.0, 0)
for inst, ps, v in (('horn', ('D3', 'A3', 'D4', 'F#4'), .72), ('trombone', ('D2', 'A2', 'D3'), .7), ('tuba', ('D1',), .7), ('trumpet', ('A4', 'D5', 'F#5'), .66)):
    for p in ps: E(48.75, inst, p, 3.4, v, 0)
for inst, ps in (('violins', ('A4', 'D5')), ('violas', ('F#4',)), ('cellos', ('D3',)), ('contrabass', ('D2',))):
    for p in ps: E(51.0, inst, p, 5.0, .4, 0)
E(49.0, 'trombone_stac', 'D2', .3, .8, .2)
# 56 end card: one last low D, bells
E(56.0, 'tuba', 'D1', 3.5, .45, 0); E(56.0, 'tubular_bells', 'D5', 3.5, .45, .2); E(56.0, 'timpani', 'D2', 2.5, .5, 0)

music = S.render(ev, dur=DUR + .5)
music = S.room(music, size=.32, mix=.14)
mt = np.arange(len(music)) / SR
music *= np.where((mt >= QUIET[0] + .9) & (mt < QUIET[1]), 0.0, 1.0)[:, None]      # hard out after the boom's tail
gate(music, *SIL)

# ============================================================ foley
fx = np.zeros((N, 2), np.float32)
R_rivet, R_whistle, R_site = load("snd_rivet"), load("snd_whistle"), load("snd_site")
RIV = [cut(R_rivet, a, a + .5) for a in (10.0, 40.0, 50.0, 80.0, 25.0, 65.0)] if R_rivet is not None else None

def metal(v=1.0, f=1.0, d=.5):
    tt = X.t_(d)
    x = sum(a * np.sin(2 * np.pi * fr * f * tt) * X.env_exp(d, tau) for fr, a, tau in [(523, .7, .18), (1187, .5, .1), (2210, .35, .06), (3330, .2, .04)])
    return X.norm(x + X.hp(X.noise(d), 2000) * X.env_exp(d, .004)) * v
def paper(v=1.0):
    d = .28; return X.norm(X.bp(X.noise(d), 900, 5000) * X.env_exp(d, .05) * (1 + .5 * np.sin(np.linspace(0, 9, int(d * SR))))) * v
def marker(d, v=1.0):
    n = X.noise(d); env = np.minimum(1, np.linspace(0, 6, len(n))) * np.minimum(1, np.linspace(6, 0, len(n)))
    return X.norm(X.bp(n, 1800, 6500) * env * (.6 + .4 * np.sin(np.linspace(0, 40 * d, len(n))))) * v

ri = 0
for e in EV:
    t, ty, g = e["t"], e["type"], e.get("g", 1.0)
    if SIL[0] <= t < SIL[1]: continue
    if ty == "slam": add(fx, X.thump(1, 52), t, .85 * g); add(fx, metal(1, .8), t, .3 * g, -.2)
    elif ty == "stamp": add(fx, X.thump(.8, 85), t, .6 * g); add(fx, X.clack(.8), t, .35 * g, .1)
    elif ty == "window": add(fx, X.whoosh(.18), t - .1, .3); add(fx, X.clack(.7), t + .06, .4)
    elif ty == "type": add(fx, X.thump(.6, 90), t, .4 * g); add(fx, X.clack(.9), t, .3 * g, .1)
    elif ty == "cut": add(fx, X.click(.8), t, .35)
    elif ty == "wipe": add(fx, X.whoosh(.25), t, .55)
    elif ty == "paper": add(fx, paper(), t, .45, -.1)
    elif ty == "marker": add(fx, marker(e.get("d", .4)), t, .35, .2)
    elif ty == "iris": add(fx, X.whoosh(.45), t, .5); add(fx, X.thump(.6, 60), t + .45, .4)
    elif ty == "girder": add(fx, metal(1, .7, .8), t, .55, -.1); add(fx, X.thump(1, 48), t, .7)
    elif ty == "cell": add(fx, metal(.6, 1 + .06 * e["k"], .35), t, .6, (-.5, 0, .5)[e["k"] % 3])
    elif ty == "stripcut": add(fx, metal(.6, .9 + .1 * e["k"]), t, .5, (-.4, 0, .4)[e["k"] % 3])
    elif ty == "freeze": add(fx, X.click(.5), t, .7); add(fx, X.thump(.7, 70), t, .5)
    elif ty == "whistle" and R_whistle is not None: add(fx, cut(R_whistle, 3.0, 5.4, .08), t, .5, .3)
    elif ty == "rivet" and RIV is not None:
        nxt = min([x["t"] for x in evt("rivet") if x["t"] > t] + [31.5]) - t
        add(fx, cut(RIV[ri % len(RIV)], 0, min(.5, nxt * .92)), t, .95 * g, (-.25, .25)[ri % 2]); ri += 1
    elif ty == "turn": add(fx, paper(.9), t, .5, .1)
    elif ty == "stand": add(fx, X.thump(.7, 120), t, .45); add(fx, paper(.6), t, .3, (-.3, -.1, .1, .3)[e["k"]])
    elif ty == "verdict": add(fx, X.thump(1, 50), t, .8); add(fx, metal(1, .75), t, .4)
    elif ty == "floor": add(fx, metal(.55, 1 + .04 * (ri % 6), .3), t, .3, (-.3, .3)[ri % 2]); ri += 1
    elif ty == "land": add(fx, X.thump(.7, 70), t, .5)
    elif ty == "final":
        add(fx, X.thump(1, 42), t, 1.0)
        if RIV is not None: add(fx, cut(RIV[0], 0, .34), t, .9)
        add(fx, metal(1, .65, 1.2), t, .5)
    elif ty == "end" and RIV is not None: add(fx, cut(RIV[2], 0, .12), t, .45)
# the rivet gun comes in a beat early (J-cut) under the question mark
if RIV is not None: add(fx, cut(RIV[3], 0, .45), 29.05, .55, .2)
gate(fx, *SIL)

# ============================================================ ambience: the site (real recording), out for the silence
tt = np.arange(N) / SR
bed = np.resize(R_site if R_site is not None else X.lp(X.brown(DUR + .5), 900) * .3, N).astype(np.float32)
env = np.clip(tt / .3, 0, 1)
env *= np.interp(tt, [0, 5, 5.2, 28, 28.2, 31.5, 32, 35.3, 35.6, 43, 43.5, 48.2, 48.25, 48.75, 49.2, 56, 59.5],
                 [.8, .8, .6, .6, 1.6, 1.6, .7, .7, .25, .25, .8, .9, 0, 0, .5, .25, 0])
amb = np.stack([bed * env, np.roll(bed, 3100) * env], 1) * .42
gate(amb, *SIL)

# ============================================================ narration: compressed, levelled, music and foley ducked under it
vo = np.zeros((N, 2), np.float32)
duck = np.zeros(N, np.float32)
for e in evt("vo"):
    x, sr = sf.read(HERE / "audio" / "vo" / f"{e['id']}.wav", dtype="float32")
    if x.ndim > 1: x = x.mean(1)
    import soxr; x = soxr.resample(x, sr, SR)
    x = X.compress(x / (np.abs(x).max() + 1e-9) * .9, thr=.3, ratio=3.0)
    x = x / (np.sqrt(np.mean(x[np.abs(x) > .02] ** 2)) + 1e-9) * .16
    add(vo, x, e["t"], 1.0, 0)
    i0 = int(e["t"] * SR); duck[max(0, i0 - int(.12 * SR)):i0 + len(x) + int(.2 * SR)] = 1
k = int(.15 * SR); duck = np.convolve(duck, np.ones(k) / k, mode="same")
music_d = music[:N] * (1 - .7 * duck)[:, None]
fx_d = fx * (1 - .35 * duck)[:, None]

# ============================================================ mix
mix = music_d * .62 + fx_d * .9 + amb + vo * 1.0
mix[:int(.025 * SR)] *= np.linspace(0, 1, int(.025 * SR))[:, None] ** 2      # no hard edge at sample 0 (AAC overshoots on it)
out = HERE / "out"; out.mkdir(exist_ok=True)
# master: bring the mix to about -14 LUFS here, then limit the hits to -1.8 dBFS, so mux.sh's loudnorm
# only trims a fraction of a dB and never pushes a transient over the true-peak ceiling
def lufs(x):
    sf.write(out / "_m.wav", x, SR)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out / "_m.wav"), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    (out / "_m.wav").unlink(); return float(r.rsplit("I:", 1)[1].split("LUFS")[0])
for _ in range(3):
    mix *= 10 ** ((-14.0 - lufs(mix)) / 20)
    for c in range(2): mix[:, c] = X.limit(mix[:, c], 10 ** (-1.8 / 20), look=.004)
print("mix loudness", round(lufs(mix), 2), "LUFS")
sf.write(out / "mix.wav", mix, SR)
st = HERE / "audio" / "stems"; st.mkdir(exist_ok=True)
for name, x in (("music", music_d * .62), ("fx", fx_d * .9), ("amb", amb), ("vo", vo)): sf.write(st / f"{name}.wav", x, SR)
def rms(x, a, b): y = x[int(a * SR):int(b * SR)]; return 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9)
print("mix", round(mix.shape[0] / SR, 2), "s  peak", round(float(np.abs(mix).max()), 3))
print("vo vs music under it (dB): ", round(rms(vo, 23.6, 27.3) - rms(music_d * .62, 23.6, 27.3), 1))
print("\n".join(S.credits(sorted({e[1] for e in ev}))))

"""Mix for 《自己倒数》 (Counting Itself Down): source audio (launch commentary + loop calls) leads, two narration lines, clock ticks, interface foley, original score (sampled instruments + synthesis).
Run: $LIB/.venv/bin/python audio/mix.py   (inside demo/; first run node core/render/events.mjs to produce events.json)
Film time t ↔ mission time M = t − 32.5. Beats = the clock's second ticks = t 0.5, 1.5, … (60 BPM, one beat per second). The score never moves time; it only adds things on the beats.
Output: out/mix.wav (48 kHz stereo) + out/stems/*.wav (source audio, narration, ticks, foley, score)."""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf
HERE = Path(__file__).resolve().parent.parent
LIB = Path(os.environ.get("LIB", HERE.parents[2]))
sys.path.insert(0, str(LIB))
from core.audio import sfx, sampler as S
from core.audio.sfx import SR, t_, env_exp, lp, hp, bp, noise, norm, add

S.seed(7); sfx._rng = np.random.default_rng(7)
ev = json.load(open(HERE / "events.json"))
DUR = ev["dur"]; T0 = 32.5; N = int(DUR * SR)
EV = ev["ev"]
def bus(): return np.zeros((N, 2))
comm, vo, ticks, fol, mus = bus(), bus(), bus(), bus(), bus()

def load(path, ss=None, d=None, ch=2):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(ss)] if ss is not None else []) + (["-t", str(d)] if d else []) + \
          ["-i", str(path), "-ac", str(ch), "-ar", str(SR), "-f", "f32le", "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)
    return a.reshape(-1, ch).astype(float)

# ——— 1. Source audio: the live-broadcast 4K soundtrack (film t = source − 14.3) ———
c = load(HERE / "raw/live4k.mp4", 14.3, DUR, ch=1)[:, 0]
c = hp(c, 90); c = sfx.compress(c / (np.abs(c).max() + 1e-9), thr=.12, ratio=3, rel=.12)
c = norm(c) * .9
f = np.ones(len(c)); f[:int(.06 * SR)] = np.linspace(0, 1, int(.06 * SR)); e0 = int((DUR - .9) * SR); f[e0:] = np.linspace(1, 0, len(f) - e0)
add(comm, c * f, 0, 1.0)

# ——— 2. Narration (Kokoro bf_emma): clean and close, distinct from the broadcast sound of the source audio ———
VO = {"n1": 13.40, "n2": 42.30}
for k, at in VO.items():
    v = load(HERE / f"audio/vo/{k}.wav", ch=1)[:, 0]
    v = norm(hp(v, 80)) * .85
    add(vo, v, at, 1.0)

# ——— 3. Clock ticks: one per whole second; T− alternates two pitches, louder in the last 10 seconds; very quiet in T+ ———
def tick(fq, v, d=.045):
    tt = t_(d); x = np.sin(2 * np.pi * fq * tt) * env_exp(d, .009) + hp(noise(d), 4000) * env_exp(d, .0015) * .6
    return norm(x) * v
for e in EV:
    if e["type"] != "tick": continue
    m = e["m"]
    if m < 0: add(ticks, tick(1850 if m % 2 else 1480, .34 if m >= -10 else .24), e["t"], 1, pan=.15 if m % 2 else -.15)
    elif m > 0: add(ticks, tick(1250, .11), e["t"], 1)

# ——— 4. Interface foley (all from window.EV) ———
def snap(v=1.0):   # cell snaps into place: metallic "click" + small low thump
    d = .08; tt = t_(d)
    x = hp(noise(d), 3000) * env_exp(d, .003) + np.sin(2 * np.pi * 2400 * tt) * env_exp(d, .01) * .4 + np.sin(2 * np.pi * 110 * tt) * env_exp(d, .03) * .7
    return norm(x) * v
def tock(v=1.0, fq=1046):   # tick mark: short woody "tock" + a little pitch
    d = .25; tt = t_(d)
    return norm(np.sin(2 * np.pi * fq * tt) * env_exp(d, .05) + bp(noise(d), 1500, 5000) * env_exp(d, .004) * .6) * v
for e in EV:
    t, ty = e["t"], e["type"]
    if ty in ("relayout", "swap"):
        add(fol, sfx.whoosh(.28, .5), t - .1, 1, pan=.3); add(fol, snap(.55), t + .3, 1)
    elif ty == "pop":
        add(fol, snap(.7), t + .02, 1, pan=-.2)
    elif ty == "check":
        add(fol, tock(.45), t, 1, pan=.35)
    elif ty == "flag":
        add(fol, sfx.whoosh(.22, .35), t - .05, 1, pan=-.3); add(fol, snap(.5), t + .2, 1)
    elif ty == "cut":
        add(fol, sfx.thump(.5, 60), t, 1)
    elif ty == "end":
        add(fol, sfx.whoosh(.5, .45), t - .15, 1)
# Sound-suppression water: white-noise bed (from film 16.5, pulled out before T0)
d = T0 - 16.4; w = lp(hp(noise(d), 600), 5000) * np.minimum(1, t_(d) / 1.5) * np.minimum(1, (d - t_(d)) / .3)
add(fol, w * .05, 16.4, 1)
# Ignition: synthesized roar + heavy hit; recedes after liftoff; from 41.7 only the roar's tail remains (silence 2), and onboard wind noise J-cuts in
add(fol, sfx.ignite(1.0), T0, .9)
rd = 41.7 - T0; r = sfx.roar(rd + 1.2, 1.0); r *= np.concatenate([np.linspace(1, .45, int(rd * SR)), np.linspace(.45, .12, len(r) - int(rd * SR))])
add(fol, r, T0, .55)
wd = DUR - 41.75; wind = lp(hp(sfx.brown(wd), 120), 2500); wind = norm(wind) * np.minimum(1, t_(wd) / .35) * np.minimum(1, (wd - t_(wd)) / 1.2)
add(fol, wind * .22, 41.75, 1, pan=-.25)

# ——— 5. Score (D minor → D major; 60 BPM) ———
SC = []   # (t, inst, pitch, dur, vel, pan[, gain])
beat = lambda m: T0 + m
# 5a Synthesized low drone: D1 + A1, low-pass opens with the countdown; dropped out 0.25 s before T0 (silence 1)
dd = T0 - .25; tt = t_(dd)
saw = lambda fq: 2 * ((fq * tt) % 1) - 1
drone = saw(36.71) * .6 + saw(55.0) * .4 + saw(73.42) * .25
out = np.zeros_like(drone); cut = np.geomspace(140, 1300, len(drone)); blk = SR // 4
for i in range(0, len(drone), blk):
    out[i:i + blk] = lp(drone[max(0, i - 4000):i + blk], float(cut[i]))[-len(drone[i:i + blk]):]
amp = np.minimum(1, tt / 1.0) * np.linspace(.5, 1, len(out)); amp[-int(.05 * SR):] *= np.linspace(1, 0, int(.05 * SR))
add(mus, out * amp * .2, 0, 1)
# 5b Handover hit (0.40): timpani + bass drum + short trombone note + tubular bells
SC += [(0.40, 'timpani', 'D2', 1.5, .85, 0), (0.40, 'gran_cassa', None, None, .6, 0), (0.40, 'trombone_stac', 'D3', .4, .8, -.2),
       (0.40, 'trombone_stac', 'A2', .4, .7, .2), (0.40, 'tubular_bells', 'D5', 3.0, .5, .3)]
# 5c Low drum on every beat (from 2.5), off-beat hi-hat added from 13.1, eighths from 22.4, sixteenths in the last 4 seconds
for m in range(-30, 0):
    t = beat(m)
    SC.append((t, 'bass_drum', None, None, .45 if m < -10 else .7, 0))
    if m >= -19: SC.append((t + .5, 'hihat', None, None, .28 if m < -10 else .38, .3))
    if m >= -10: SC.append((t + .25, 'hihat', None, None, .2, -.3)); SC.append((t + .75, 'hihat', None, None, .2, -.3))
    if m >= -4:
        for j in (.125, .375, .625, .875): SC.append((t + j, 'snare', None, None, .16 + .05 * (m + 4), .1))
# 5d Data bars grow (7.7): short rising brass chord
SC += [(7.7, 'horn_stac', 'D4', .3, .6, -.2), (7.95, 'horn_stac', 'F4', .3, .65, 0), (8.2, 'horn_stac', 'A4', .5, .7, .2), (8.2, 'trombone_stac', 'D3', .5, .6, 0)]
# 5e The count: one tom hit per number (on the same beat as the cell opening)
for e in EV:
    if e["type"] == "pop": SC.append((e["t"], 'toms', 0, None, .85, -.1)); SC.append((e["t"], 'timpani', 'A1', 1.0, .55, .1))
SC += [(26.46, 'gran_cassa', None, None, .7, 0), (26.46, 'tuba', 'D1', 5.4, .45, 0), (26.46, 'trombone', 'A2', 5.4, .35, .2)]   # RS-25: long low-brass note
# 5f Timpani roll from T−3, building until 0.25 s before T0
for i in range(int(2.75 / .07)):
    t = beat(-3) + i * .07; SC.append((t, 'timpani', 'D2', .2, .25 + .6 * (i * .07 / 2.75) ** 2, (-1) ** i * .15))
# 5g T0: big chord (D major) + bass drum + cymbal; afterwards long brass notes support the commentary
SC += [(T0, 'gran_cassa', None, None, 1.0, 0), (T0, 'bass_drum', None, None, 1.0, 0), (T0, 'crash', None, None, .9, .2), (T0, 'timpani', 'D2', 3.0, 1.0, 0),
       (T0, 'tuba', 'D1', 8.5, .8, 0), (T0, 'trombone', 'D2', 8.5, .7, -.2), (T0, 'trombone', 'A2', 8.5, .65, .2),
       (T0, 'horn', 'D4', 8.5, .6, -.3), (T0, 'horn', 'F#4', 8.5, .55, .3), (T0, 'horn', 'A4', 8.5, .5, 0), (T0, 'tubular_bells', 'D5', 5.0, .6, .2)]
for m in range(2, 9, 2): SC.append((beat(m), 'bass_drum', None, None, .45, 0))                   # half time
SC += [(36.36, 'horn', 'B3', 5.0, .45, -.2), (36.36, 'trombone', 'G2', 5.0, .45, .2), (39.5, 'horn', 'A3', 2.0, .45, 0), (39.5, 'horn', 'C#4', 2.0, .4, .2)]
# 5h From 42.0: new texture — plucked bass figure + light hi-hat; the second countdown
BASS = ['D2', 'D2', 'A1', 'C2']
for i, m in enumerate(range(10, 23)):
    t = beat(m); SC.append((t, 'contrabass_pizz', BASS[i % 4], .8, .7, 0)); SC.append((t + .5, 'hihat', None, None, .18, .3))
    if i % 2 == 0: SC.append((t, 'bass_drum', None, None, .4, 0))
for e in EV:
    if e["type"] == "check" and e["t"] > T0: SC.append((e["t"], 'glockenspiel', 'A5', .8, .45, .3))
# 5i Houston takes over (53.78): tubular bells + French horn
SC += [(53.78, 'tubular_bells', 'A4', 4.0, .55, -.2), (53.78, 'tubular_bells', 'D5', 4.0, .5, .2), (53.78, 'horn', 'D4', 3.0, .45, 0), (53.78, 'timpani', 'D2', 1.2, .6, 0)]
# 5j End card (54.0): resolves to D major
SC += [(54.0, 'tuba', 'D1', 4.5, .6, 0), (54.0, 'trombone', 'A2', 4.5, .5, -.2), (54.0, 'horn', 'F#4', 4.5, .5, .2), (54.0, 'horn', 'D4', 4.5, .5, -.1),
       (54.0, 'glockenspiel', 'D6', 2, .4, .3), (54.5, 'glockenspiel', 'A5', 2, .35, .3), (55.0, 'glockenspiel', 'F#5', 2, .3, .3)]
m = S.render(SC, dur=DUR, master=False)
mus += m[:N] * .9
f = np.ones(N); e0 = int((DUR - 1.4) * SR); f[e0:] = np.linspace(1, 0, N - e0) ** 1.5; mus *= f[:, None]

# ——— 6. Balance: score and foley pulled down under speech (sidechain) ———
def envelope(x, win=.25):
    k = int(win * SR); p = np.convolve(np.abs(x).mean(1), np.ones(k) / k, mode='same'); return p
sp = envelope(comm + vo); sp = sp / (sp.max() + 1e-9)
duck = 1 - .5 * np.clip(sp * 4, 0, 1)
rms = lambda x: np.sqrt(np.mean(x ** 2) + 1e-12)
def at_db(x, ref, db): return x * (rms(ref) / (rms(x) + 1e-12)) * 10 ** (db / 20)
post = np.ones(N); post[int(T0 * SR):] = 10 ** (3.5 / 20); post[int(42.0 * SR):] = 2.5 * 10 ** (3.5 / 20);   # +3.5 dB overall after liftoff post = np.convolve(post, np.ones(SR // 5) / (SR // 5), mode="same")
mus = at_db(mus, comm, -7.5) * duck[:, None] * post[:, None]
fol = at_db(fol, comm, -11) * (.6 + .4 * duck[:, None])
ticks = at_db(ticks, comm, -16)
vo = vo * (rms(comm[np.abs(comm).mean(1) > .02]) / (rms(vo[np.abs(vo).mean(1) > .02]) + 1e-9)) * 1.05
mix = comm + vo + ticks + fol + mus
# Pre-mastering: push the whole mix to about −14 LUFS based on measured loudness, then use a look-ahead limiter to keep peaks below −2 dBFS (so mux.sh's loudnorm barely has to change the gain)
def lufs(x):
    sf.write(HERE / "out/_tmp.wav", x.astype(np.float32), SR)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(HERE / "out/_tmp.wav"), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    os.remove(HERE / "out/_tmp.wav")
    return float([l for l in r.splitlines() if l.strip().startswith("I:")][-1].split()[1])
(HERE / "out").mkdir(exist_ok=True)
# Limiter: linked stereo, 5 ms look-ahead, 150 ms release (a smooth gain curve, so the ignition hit isn't flattened wave by wave)
from scipy.ndimage import maximum_filter1d
from scipy.signal import lfilter
def limit2(x, ceil):
    look = int(.005 * SR); pk = maximum_filter1d(np.abs(x).max(1), size=2 * look + 1)
    gr = np.minimum(1, ceil / np.maximum(pk, 1e-9))
    a = np.exp(-1 / (.150 * SR)); sm = lfilter([1 - a], [1, -a], 1 - gr)       # release: gain reduction recovers over 150 ms
    gr2 = 1 - np.maximum(1 - gr, sm)
    return x * gr2[:, None]
for _ in range(3):
    mix *= 10 ** ((-14.0 - lufs(mix)) / 20)
    mix = limit2(mix, .68)
gr_t0 = 20 * np.log10(np.abs(mix[int(T0 * SR):int((T0 + .6) * SR)]).max() / .68 + 1e-9)
print("peak headroom at ignition (dB vs ceiling):", round(float(gr_t0), 2))
(HERE / "out/stems").mkdir(parents=True, exist_ok=True)
for name, b in [("commentary", comm), ("voice", vo), ("ticks", ticks), ("foley", fol), ("music", mus)]:
    sf.write(HERE / f"out/stems/{name}.wav", b.astype(np.float32), SR)
sf.write(HERE / "out/mix.wav", mix.astype(np.float32), SR)
print("mix ok", round(DUR, 2), "s, peak", round(float(np.abs(mix).max()), 3))

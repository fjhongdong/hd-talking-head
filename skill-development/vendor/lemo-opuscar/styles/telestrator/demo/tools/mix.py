#!/usr/bin/env python3
"""Mix for "Freeze Frame" (《定格》): original sound (crowd + beIN commentary) + English voice-over + sampled score + sound effects → out/mix.wav (48 kHz stereo).
Music rule: while the picture plays the drum kit runs; on a freeze the drums stop, leaving only one "freeze hit" and the hi-hat — the music freezes along with the picture.
The hand-written times for the long third-goal section (live replay → review notes) are written in that section's own time (4.4–33.0 s); T() shifts them as a block onto the timeline in timeline.json.
Run with the .venv at the library root: .venv/bin/python <demo>/tools/mix.py"""
import sys, os, json
import numpy as np, soundfile as sf, soxr
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.environ.get('LIB') or os.path.dirname(os.path.dirname(os.path.dirname(D))); sys.path.insert(0, LIB)
from core.audio import sampler as S
from core.audio.sfx import SR, add, lp, hp, bp, noise, env_exp, t_, thump, whoosh, step, pop, norm, limit

TL = json.load(open(f'{D}/timeline.json')); DUR = TL['dur']; N = int(DUR * SR)
seg = {s['id']: s for s in TL['seg']}
O3, ON = seg['live']['t0'] - 4.4, seg['notes']['t0'] - 23.4      # section time → timeline
def T(x): return x + O3 if 4.4 <= x < 23.4 else x + ON if 23.4 <= x < 33.0 else x
S.seed(7)

def stereo(n=N): return np.zeros((n, 2), np.float32)

# ---------- original sound ----------
o, osr = sf.read(f'{D}/audio/orig.wav', dtype='float32')
if osr != SR: o = soxr.resample(o, osr, SR)
def osl(a, b): return o[int(a * SR):int(b * SR)].copy()
o2, osr2 = sf.read(f'{D}/audio/orig2.wav', dtype='float32')          # official highlights 108–153 s: original sound of the first two goals
if osr2 != SR: o2 = soxr.resample(o2, osr2, SR)
def osl2(a, b): return o2[int((a - 108) * SR):int((b - 108) * SR)].copy()   # arguments are in highlights time (seconds)
def fade(x, fi=.03, fo=.06):
    n = len(x); a = min(int(fi * SR), n // 2); b = min(int(fo * SR), n // 2)
    if a: x[:a] *= np.linspace(0, 1, a)[:, None]
    if b: x[-b:] *= np.linspace(1, 0, b)[:, None]
    return x
def put(buf, x, at, g=1.0):
    s = int(at * SR); e = min(len(buf), s + len(x)); buf[s:e] += x[:e - s] * g

orig = stereo()
# first goal: live main-camera sound (commentary + crowd); during the freeze only the low-passed crowd remains; when play resumes, cut into the goal section
put(orig, fade(osl2(113.12, 114.72 + .05), .02, .08), seg['g1live']['t0'], 2.2)
put(orig, fade(osl2(114.72, 116.6), .02, .3), seg['g1go']['t0'], 2.4)
# second goal: during the split screen use the original sound of the main-camera free-kick section; after the goal, cut to crowd and commentary
put(orig, fade(osl2(141.16, 142.6), .05, .1), seg['g2split']['t0'], 1.8)
put(orig, fade(osl2(142.24, 145.44), .02, .4), seg['g2go']['t0'], 2.3)   # the crowd on the ball hitting the net is aligned to frame F057 in the picture
put(orig, fade(osl(0.0, 4.6), .01, .08), seg['live']['t0'], 2.4)                 # third goal live: original sound throughout
# rewind: the 4.6 s of live sound reversed and squeezed into 0.6 s (the squeal of a tape rewinding)
rv = osl(0.0, 4.6)[::-1]; rv = soxr.resample(rv, SR * 4.6 / .6, SR)[:int(.6 * SR)]
put(orig, fade(rv, .02, .05), seg['rewind']['t0'], .35)
# crowd bed for the analysis sections: crowd sound from before the commentator starts talking (0–2 s), low-passed, looped
bed = osl(0.0, 2.0); bed = np.stack([lp(bed[:, c], 900) for c in range(2)], 1).astype(np.float32)
def loopbed(buf, a, b, g):
    t = a
    while t < b:
        L = min(2.0, b - t)
        if L < .3: break
        x = fade(bed[:int(L * SR)].copy(), .25, .25); put(buf, x, t, g); t += 1.75
loopbed(orig, seg['g1fz']['t0'], seg['g1fz']['t1'], .5)
loopbed(orig, seg['g2fz']['t0'], seg['g2fz']['t1'], .5)
loopbed(orig, seg['fz1']['t0'], seg['flight']['t0'] + .9, .5)
loopbed(orig, seg['map']['t0'], seg['map']['t1'], .3)
put(orig, fade(osl(3.9, 6.0), .05, .4), T(19.40), 1.3)                                # the moment the ball hits the net: crowd erupts + "GOL"
put(orig, fade(osl(10.0, 13.6), .15, .3), seg['rep1']['t0'], 2.0)                   # original sound of the reverse-angle replay
loopbed(orig, seg['notes']['t0'], seg['notes']['t1'], .3)
put(orig, fade(osl(4.9, 7.95), .05, .5), seg['end']['t0'], 1.8)                    # 67′ close: "Mükemmel bir gol! Süper bir gol!"
loopbed(orig, seg['card']['t0'] + .2, seg['card']['t1'], .32)                        # shared end card: low-passed crowd as the bed

# ---------- voice-over ----------
vo = stereo(); vdur = json.load(open(f'{D}/audio/vo/dur.json'))
for v in TL['vo']:
    x, vsr = sf.read(f'{D}/audio/vo/{v["id"]}.wav', dtype='float32')
    if x.ndim > 1: x = x.mean(1)
    if vsr != SR: x = soxr.resample(x, vsr, SR)
    x = hp(x, 90).astype(np.float32)
    add(vo, x, v['t'], 1.0, 0)
vmask = np.zeros(N, np.float32)
for v in TL['vo']:
    a, b = int(v['t'] * SR), int((v['t'] + vdur[v['id']]) * SR); vmask[a:b] = 1
k = int(.12 * SR); vmask = np.convolve(vmask, np.ones(k) / k, 'same')
duck = (1 - .55 * vmask)[:, None]

# ---------- score (real instrument samples, E minor, 120 BPM) ----------
B = .5   # one beat
ev = []
def groove(a, b, g=1.0, half=False, hat=True):
    """Beats counted from a within [a,b): kick/snare/hihat + electric bass. half=True is half time (analysis sections)"""
    t = a; i = 0
    bass = ['E1', 'E1', 'G1', 'A1', 'E1', 'E1', 'B1', 'A1']
    while t < b - 1e-6:
        beat = i % 4
        if hat: ev.append((t, 'drum_kit', 'hi_hat_closed', None, .45 * g, .3)); ev.append((t + B / 2, 'drum_kit', 'hi_hat_closed', None, .3 * g, .3))
        if half:
            if beat == 0: ev.append((t, 'drum_kit', 'kick_drum_left', None, .8 * g, 0))
            if beat == 2: ev.append((t, 'drum_kit', 'snare_1', None, .55 * g, -.05))
            if beat in (0, 2): ev.append((t, 'electric_bass', bass[(i // 2) % 8], B * 1.8, .7 * g, 0))
        else:
            if beat in (0, 2) or (beat == 1 and i % 8 == 5): ev.append((t, 'drum_kit', 'kick_drum_left', None, .9 * g, 0))
            if beat in (1, 3): ev.append((t, 'drum_kit', 'snare_1', None, .75 * g, -.05))
            ev.append((t, 'electric_bass', bass[i % 8], B * .8, .75 * g, 0))
            if beat == 3: ev.append((t + B / 2, 'electric_bass', bass[(i + 1) % 8], B * .4, .6 * g, 0))
        t += B; i += 1
def stab(t, g=1.0, big=False):
    """Short brass stab + timpani: E minor tonic chord"""
    for p in ['E4', 'G4', 'B4'] + (['E5'] if big else []): ev.append((t, 'trumpet_stac', p, .3, .85 * g, .15))
    for p in ['E3', 'B3']: ev.append((t, 'trombone_stac', p, .35, .85 * g, -.15))
    ev.append((t, 'timpani', 'E3', 1.2, .9 * g, 0))
    if big: ev.append((t, 'drum_kit', 'crash_left', None, .8 * g, -.3))

# opening sting: a slash at 0.12 → a stamp hit at 0.44
stab(0.44, 1.0, big=True); ev.append((0.0, 'drum_kit', 'tom_1', None, .5, .2)); ev.append((0.22, 'drum_kit', 'tom_2', None, .6, -.2))
for k_ in range(6): ev.append((1.0 + k_ * .1, 'drum_kit', 'snare_2', None, .25 + .08 * k_, 0))   # 1.0–1.5 snare fill, leading into the match card
groove(seg['record']['t0'], seg['record']['t1'], 1.0)
R0 = seg['record']['t0']
for tt in [R0 + .8, R0 + 1.0, R0 + 1.2]: ev.append((tt, 'glockenspiel', 'B6', .4, .6, .25))  # score digits ticking up
groove(seg['g1live']['t0'], seg['g1live']['t1'], .45)
groove(seg['g1go']['t0'], seg['g1go']['t1'], .45)
groove(seg['g2split']['t0'], seg['g2split']['t1'], .55, half=True)
groove(seg['g2go']['t0'], seg['g2go']['t1'], .45)
GOALT = [seg['g1go']['t0'] + (125 - 106) / ((seg['g1go']['f1'] - 106) / (seg['g1go']['t1'] - seg['g1go']['t0'])),
         seg['g2go']['t0'] + (57 - 46) / ((seg['g2go']['f1'] - 46) / (seg['g2go']['t1'] - seg['g2go']['t0']))]
for gt in GOALT:                                  # first two goals hitting the net: big brass chord + cymbal + glockenspiel (on the same frame as the score bar flip in the page)
    stab(gt, .8, big=True); ev.append((gt + .05, 'glockenspiel', 'E6', .5, .45, .2))
VART = seg['g2go']['t0'] + .95                     # VAR stamp: timpani + low trombone
ev.append((VART, 'timpani', 'E2', 1.0, .9, 0)); ev.append((VART, 'trombone_stac', 'E2', .5, .8, -.1)); ev.append((VART + .02, 'drum_kit', 'crash_left', None, .5, -.2))
groove(seg['live']['t0'], seg['live']['t1'], .45)
# analysis sections: half-time groove while playing; on a freeze only the hi-hat + freeze hit
for sid in ['slow1', 'slow2', 'flight']: groove(seg[sid]['t0'], seg[sid]['t1'], .7, half=True)
for sid in ['g1fz', 'g2fz', 'fz1', 'fz2', 'fz3', 'fz4']:
    s_ = seg[sid]; stab(s_['t0'], .55)
    t = s_['t0'] + B
    while t < s_['t1'] - .05: ev.append((t, 'drum_kit', 'hi_hat_closed', None, .25, .3)); t += B / 2
groove(seg['rep1']['t0'], seg['rep1']['t1'], .55, half=True); groove(seg['rep2']['t0'], seg['rep2']['t1'], .55, half=True)
# top-down tactics board: freeze hit → timpani roll crescendo while it flattens → one glockenspiel note as each of the three points lands → half-time groove once the board has settled
M0 = seg['map']['t0']; stab(M0, .55)
for i in range(14): ev.append((M0 + .55 + i * .065, 'timpani', 'E2', .3, .25 + .04 * i, 0))
stab(M0 + 1.45, .7)
for tt, p in [(M0 + 1.45, 'B5'), (M0 + 1.65, 'D6'), (M0 + 1.85, 'E6')]: ev.append((tt, 'glockenspiel', p, .6, .5, .2))
groove(M0 + 2.5, seg['map']['t1'], .5, half=True)
groove(seg['notes']['t0'], seg['notes']['t1'], .6)
# end card: big chord + long horn/cello notes to close
stab(seg['end']['t0'], 1.0, big=True)
for p in ['E3', 'B3', 'G4']: ev.append((seg['end']['t0'] + .05, 'horn', p, 2.6, .55, 0))
ev.append((seg['end']['t0'] + .05, 'cellos', 'E2', 2.7, .5, 0))
ev.append((seg['end']['t0'] + 2.0, 'drum_kit', 'ride_bell_left', None, .35, .3))
# shared end card: one timpani hit as the diagonal band comes in + two glockenspiel "closing strokes"; long horn/cello E minor notes laid under to the end of the film
C0 = seg['card']['t0']
ev.append((C0, 'timpani', 'E3', 1.6, .55, 0))
CL = seg['card']['t1'] - C0
for p in ['E3', 'B3', 'E4']: ev.append((C0 + .05, 'horn', p, CL - .3, .42, 0))
ev.append((C0 + .05, 'cellos', 'E2', CL - .2, .42, 0))
ev.append((C0 + .2, 'glockenspiel', 'E6', .8, .42, .2)); ev.append((C0 + .45, 'glockenspiel', 'B6', 1.0, .36, .25))
ev.append((C0 + .5, 'drum_kit', 'ride_bell_left', None, .25, .3))
music = S.render(ev, dur=DUR + 3)[:N].astype(np.float32)
music = S.room(music, size=.35, mix=.12)[:N]
mfade = np.ones(N, np.float32); a = int((DUR - 1.2) * SR); mfade[a:] = np.linspace(1, 0, N - a) ** 1.5
music *= mfade[:, None]

# ---------- sound effects ----------
fx = stereo()
def squeak(d, v=1.0, seed=0):
    """Marker squeaking on a glass board: 2–5 kHz band-passed noise + irregular judder"""
    rng = np.random.default_rng(seed); n = int(d * SR); tt = np.arange(n) / SR
    x = bp(rng.standard_normal(n), 2200, 5200)
    am = .55 + .45 * np.sin(2 * np.pi * (24 + 8 * rng.random()) * tt + rng.random() * 6) * (1 + .3 * np.sin(2 * np.pi * 3.1 * tt))
    e = np.minimum(1, tt / .02) * np.minimum(1, (d - tt) / .04)
    return (norm(x * am * e) * v).astype(np.float32)
def scribble(d, v=1.0, seed=0):
    """Pen writing: short scratches of friction on paper"""
    rng = np.random.default_rng(seed); n = int(d * SR); x = bp(rng.standard_normal(n), 1500, 6000)
    g = np.zeros(n); p = 0
    while p < n: L = int(rng.uniform(.03, .09) * SR); g[p:p + L] = rng.uniform(.4, 1); p += L + int(rng.uniform(.01, .04) * SR)
    g = np.convolve(g[:n], np.ones(240) / 240, 'same')
    return (norm(x * g) * v).astype(np.float32)
def shutter(v=1.0):
    d = .09; tt = t_(d); x = hp(noise(d), 1500) * (env_exp(d, .004) + .6 * np.roll(env_exp(d, .006), int(.035 * SR)))
    return (norm(x) * v).astype(np.float32)
NT = seg['notes']['t0']
strokes = [(.12, .36, .7), (R0 + 1.35, .3, .4), (NT + .35, .25, .35), (NT + 1.6, .4, .35)] + [(T(a), d, v) for a, d, v in [(9.95, .55, .45), (10.6, .4, .35), (13.35, .35, .35), (13.65, .5, .35),
           (16.35, .4, .35), (16.7, .3, .3), (16.8, .55, .45), (21.69, .25, .35), (21.79, .35, .4)]]
G1, G2, M0 = seg['g1fz']['t0'], seg['g2fz']['t0'], seg['map']['t0']
strokes += [(G1 + .12, .48, .45), (G1 + .55, .3, .3), (G1 + .7, .3, .35),                       # first goal: ball path, gap, run
            (G2 + .1, .4, .4), (G2 + .55, .3, .35),                                            # second goal: one ball path in each of the two panels + header arrow
            (M0 + .08, .5, .35), (M0 + 1.5, .35, .3), (M0 + 1.7, .35, .3)]                      # tactics board: tracing the pitch lines, the shot line
for i, (a_, d_, v_) in enumerate(strokes): add(fx, squeak(d_, v_, i), a_, .55, (i % 3 - 1) * .2)
for i, (a_, d_) in enumerate([(.02, .38), (.3, .35), (.6, .35), (.9, .35), (1.5, .4)]): add(fx, scribble(d_, .5, 50 + i), NT + a_, .5, .1)   # review card revealed line by line
for sid in ['g1fz', 'g2fz', 'fz1', 'fz2', 'fz3', 'fz4', 'map']: add(fx, thump(1, 58), seg[sid]['t0'], .7); add(fx, shutter(1), seg[sid]['t0'], .45)
for tt in [T(x) for x in [9.72, 12.21, 13.65, 13.8, 16.55, 20.0, 20.25]] + [G1 + .3, G1 + .6, G2 + .3, G2 + .5, M0 + 1.2, M0 + 1.45, M0 + 1.65, M0 + 1.85]: add(fx, pop(1), tt, .18, .1)
for tt in [T(x) for x in [10.1, 13.9, 17.1, 21.74]] + [G1 + .85, G1 + 1.1, G2 + .5, G2 + .8]: add(fx, step(1), tt, .25)   # labels landing
for tt in [seg[k]['t0'] for k in ['record', 'g1live', 'g2split', 'live', 'rep1', 'notes', 'end', 'card']]: add(fx, whoosh(.34, 1), tt - .17, .35)   # graphics-package diagonal-band transitions
add(fx, whoosh(.9, 1), M0 + .5, .3)                                                # tactics board flattening
add(fx, thump(1, 46), VART, .8)                                                    # VAR stamp landing
t = T(15.0)
while t < T(16.2): add(fx, step(.6), t, .18, .3); t += .2                          # stopwatch
add(fx, whoosh(.5, 1), T(18.2), .3)                                                # the strike
add(fx, (lp(noise(.25), 2500) * env_exp(.25, .05)).astype(np.float32), T(19.46), .35)  # ball hits the net
w = (bp(noise(.6), 300, 2200) * np.sin(np.pi * t_(.6) / .6)).astype(np.float32)     # rewind motor
add(fx, norm(w), T(9.0), .25)

# ---------- bus ----------
mix = orig * duck * 1.0 + vo * 1.25 + music * duck * .62 + fx * .9
tail = np.ones(N, np.float32); a = int((DUR - .45) * SR); tail[a:] = np.linspace(1, 0, N - a) ** 2   # fade to black together with the picture
mix *= tail[:, None]
for c in range(2): mix[:, c] = limit(mix[:, c], .42)   # limit peaks first: loudnorm in the mux raises everything by ~6 dB
os.makedirs(f'{D}/out', exist_ok=True); sf.write(f'{D}/out/mix.wav', mix, SR, subtype='PCM_24')
print('mix', mix.shape, 'peak', float(np.abs(mix).max()))
print(S.credits(sorted({e[1] for e in ev})))

#!/usr/bin/env python3
"""Mix of score, sound effects, source audio and narration for 《兴登堡号：四分钟与三十二秒》 ("Hindenburg: Four Minutes and Thirty-two Seconds") → out/mix.wav (48 kHz stereo).
All timings come from ../film.json. The score uses core/audio/sampler (VSCO 2 CE / VCSL, CC0); sound effects use core/audio/sfx (procedurally synthesized).
Layers (bottom → top): bass drone → rhythm (pendulum tick / pizzicato ostinato) → harmonic pad → sound effects → source audio / narration (music ducks)."""
import json, os, sys
import numpy as np, soundfile as sf, soxr
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.environ.get('LIB') or os.path.abspath(os.path.join(D, '../../..'))
sys.path.insert(0, LIB)
from core.audio import sampler as S
from core.audio.sfx import SR, add, bp, hp, lp, noise, env_exp, t_, whoosh, thump, norm, limit, brown

F = json.load(open(os.path.join(D, 'film.json'))); SEC = F['sections']; DUR = F['dur']
N = int(DUR * SR); mus = np.zeros((N, 2), np.float32); fx = np.zeros((N, 2), np.float32); voc = np.zeros((N, 2), np.float32)
S.seed(7)
ev = []   # (t, inst, pitch, dur, vel, pan[, gain])
def E(*a): ev.append(a)

# ── Score ──
# Cold open: 0.0 freeze frame slams in (bass drum + timpani + short low-strings stab); 0.6 / 0.9 / 1.2 evidence slams in (wood block)
E(0.0, 'gran_cassa', 'hit', 1.6, .95, 0, 1.0); E(0.0, 'timpani', 'D2', 1.8, .9, 0, .9); E(0.0, 'contrabass', 'D2', .5, .9, -.2, .8); E(0.0, 'cellos', 'D3', .5, .8, .2, .6)
for tt in (0.6, 0.9, 1.2): E(tt, 'woodblock', 'a', .2, .7, .3, .55); E(tt, 'timpani', 'A2', .6, .5, 0, .45)
# Title: settles at 2.4, bass drone on D (until 12.3)
E(2.4, 'timpani', 'D2', 2.0, .75, 0, .8); E(2.4, 'sus_cymbal', 'roll', 1.4, .35, .2, .25)
E(2.4, 'contrabass', 'D2', 9.9, .55, -.2, .55); E(2.4, 'cellos', 'A2', 9.9, .5, .2, .45)
E(2.6, 'violins_trem', 'A5', 3.2, .25, .4, .18)
# Waiting + position: pizzicato ostinato (eighth note = 0.25 s), harmony Dm → Bb → Gm → A
chords = [(6.0, ['D4', 'F4', 'A4', 'F4']), (10.3, ['D4', 'F4', 'A4', 'C5']), (12.3, ['D4', 'F4', 'Bb4', 'F4']), (14.3, ['D4', 'G4', 'Bb4', 'G4']), (16.3, ['C#4', 'E4', 'A4', 'E4'])]
for i, (t0, pat) in enumerate(chords):
    t1 = chords[i + 1][0] if i + 1 < len(chords) else 18.6
    k = 0; tt = t0
    while tt < t1 - .01: E(tt, 'violas_pizz', pat[k % 4], .3, .42 + .12 * (k % 4 == 0), .25, .45); k += 1; tt += .25
for t0, root, d in [(12.3, 'Bb1', 2.0), (14.3, 'G2', 2.0), (16.3, 'A1', 2.3)]: E(t0, 'contrabass', root if root != 'Bb1' else 'Bb2', d, .5, -.2, .5)
E(12.3, 'cellos', 'F3', 6.3, .4, .2, .35)
# Four minutes: pizzicato stops, string tremolo builds up (E5/F5 minor second) + low heartbeat (every 1 s)
E(18.6, 'violins_trem', 'E5', 5.0, .3, .35, .25); E(19.8, 'violins_trem', 'F5', 3.8, .35, -.35, .25); E(18.6, 'cellos', 'D3', 5.0, .45, .1, .4)
for tt in np.arange(18.8, 23.6, 1.0): E(float(tt), 'contrabass_pizz' if 'contrabass_pizz' in S.REG else 'cellos_pizz', 'D2', .5, .75, 0, .7)
# Point of ignition: heavy bass-drum hit at 23.8; after that only the low D remains (source audio at 24.4)
E(23.8, 'gran_cassa', 'hit', 2.0, .9, 0, .9); E(23.8, 'timpani', 'D2', 2.2, .85, 0, .8); E(23.8, 'contrabass', 'D2', 8.0, .4, 0, .45)
# The five "matches": rising glockenspiel
for i, p in enumerate(['D6', 'F6', 'A6', 'C7', 'D7']): E(30.0 + .12 * i, 'glockenspiel', p, 1.2, .55, -.3 + .15 * i, .5)
E(28.0, 'cellos', 'D3', 3.8, .35, .1, .3); E(28.0, 'violas', 'A3', 3.8, .3, -.1, .25)
# Thirty-two seconds: rising string pad; heavy hit at ground impact 36.5, near silence afterwards
E(31.8, 'cellos', 'D3', 4.7, .35, .1, .4); E(32.6, 'violas', 'F3', 3.9, .35, -.1, .3); E(33.6, 'violins', 'A4', 2.9, .35, .3, .25); E(34.6, 'violins', 'C5', 1.9, .4, -.3, .22)
E(36.5, 'gran_cassa', 'hit', 2.2, 1.0, 0, 1.0); E(36.5, 'timpani', 'D2', 2.2, .9, 0, .9); E(36.5, 'contrabass', 'D2', 2.1, .5, 0, .45)
# Inquiry: slow harmony Dm – Bb – Gm – A
for t0, notes in [(38.6, ['D3', 'A3', 'F4']), (40.6, ['Bb2', 'F3', 'D4']), (42.6, ['G2', 'D3', 'Bb3']), (44.6, ['A2', 'E3', 'C#4'])]:
    E(t0, 'cellos', notes[0], 2.1, .4, .15, .4); E(t0, 'violas', notes[1], 2.1, .35, -.1, .3); E(t0, 'violins', notes[2], 2.1, .3, .3, .22)
    E(t0, 'harp', notes[0], 2.0, .5, -.2, .3)
# People: only one cello's long note remains
E(45.6, 'cellos', 'D3', 6.6, .3, 0, .35)
# Summary map + end card: Dm(add9) spreads out, vibraphone arpeggio
E(52.4, 'gran_cassa', 'hit', 2.0, .5, 0, .45); E(52.4, 'glockenspiel', 'D6', 1.5, .5, 0, .4)
for p, pan in [('D2', 0), ('D3', -.2), ('A3', .2), ('E4', -.3), ('F4', .3)]: E(52.4, 'cellos' if p != 'D2' else 'contrabass', p, 7.2, .4, pan, .38)
E(52.6, 'violins', 'A4', 6.8, .3, .35, .2)
for i, p in enumerate(['D4', 'A4', 'E5', 'F5', 'A5', 'D6']): E(52.5 + .25 * i, 'vibraphone', p, 2.5, .45, -.3 + .12 * i, .35)
for i, p in enumerate(['D3', 'A3', 'E4', 'F4']): E(55.6 + .5 * i, 'harp', p, 3.0, .45, -.2 + .12 * i, .35)

mus += S.render(ev, dur=DUR, master=False)[:N]
mus = S.room(mus, size=.5, mix=.2)

# ── Sound effects (procedurally synthesized)──
def tick(v=1.0, f=2400):  # pendulum / stopwatch
    d = .03; tt = t_(d); return (hp(noise(d), 1800) * env_exp(d, .003) + np.sin(2 * np.pi * f * tt) * env_exp(d, .004) * .6) * v
def paper(v=1.0):         # document enters
    d = .25; return bp(noise(d), 1200, 6000) * env_exp(d, .05) * (1 - np.exp(-t_(d) / .01)) * v
def shutter(v=1.0):       # photo enters
    d = .09; a = hp(noise(d), 2000) * env_exp(d, .006); b = np.pad(hp(noise(.05), 1500) * env_exp(.05, .005), (int(.045 * SR), 0))[:len(a)]
    return norm(a + b * .8) * v
def morse(seq='..', f=820, v=1.0):  # telegraph "dit-dah"
    out = [];
    for c in seq: d = .05 if c == '.' else .14; tt = t_(d); s = np.sin(2 * np.pi * f * tt); s[:96] *= np.linspace(0, 1, 96); s[-96:] *= np.linspace(1, 0, 96); out += [s, np.zeros(int(.05 * SR))]
    return np.concatenate(out) * .5 * v
def typekey(v=1.0):
    d = .035; return norm(bp(noise(d), 900, 5000) * env_exp(d, .004) + np.sin(2 * np.pi * 180 * t_(d)) * env_exp(d, .008) * .4) * v
def rewind(d=.4, v=1.0):  # rewind: falling band-passed noise + motor whine
    tt = t_(d); f = 3000 * np.exp(-tt * 3.5) + 300; ph = 2 * np.pi * np.cumsum(f) / SR
    return (bp(noise(d), 600, 4000) * .5 + np.sin(ph) * .3 + np.sin(ph * 2.01) * .15) * np.sin(np.pi * tt / d) * v

add(fx, thump(1.0, 48), 0.0, .6)
for tt in (0.6, 1.2): add(fx, paper(1), tt, .45, .3)
add(fx, shutter(1), 0.9, .6, -.3)
add(fx, whoosh(.32, 1), 1.48, .35, 0)
add(fx, rewind(.42, 1), 1.98, .55, 0)
add(fx, whoosh(.3, 1), 2.38, .3)
# Telegrams: morse + typing for each one
for g in [6.35, 7.0, 7.65, 8.3]:
    add(fx, morse('.-.', 820), g - .02, .5, .2)
    for k in range(10): add(fx, typekey(.8 + .2 * np.random.rand()), g + .04 + k * .042, .32, .25 - .05 * k)
for tt in np.arange(6.5, 12.3, .5): add(fx, tick(.6), float(tt), .22, -.2)   # pendulum on the minute scale
add(fx, whoosh(.4, 1), 12.25, .35)   # cut to the map
add(fx, shutter(1), 13.0, .5, .3); add(fx, paper(1), 14.8, .4, -.2); add(fx, shutter(1), 14.6, .45, .3)
for k in range(9): add(fx, bp(noise(.08), 2500, 7000) * env_exp(.08, .03) * .4, 14.9 + k * .1, .25, -.2)  # plan-view lines being drawn
for tt in np.arange(18.6, 23.6, .5): add(fx, tick(1.0, 2600 if int(tt * 2) % 2 == 0 else 2200), float(tt), .4, 0)   # four minutes: clock
add(fx, paper(1), 18.95, .45, .2)
add(fx, whoosh(.25, 1), 23.72, .3)   # cut to the point of ignition
add(fx, paper(1), 24.0, .45, -.3); add(fx, shutter(1), 24.4, .4, .1); add(fx, shutter(1), 24.8, .45, .35); add(fx, paper(1), 25.8, .4, -.3)
# Thirty-two seconds: one hit per event second (32 hits squeezed into 4.3 s), a heavier hit every 5 seconds
def ev_t(k): return 32.2 + k * 0.6 / 7 if k <= 7 else 32.8 + (k - 7) * 3.7 / 25   # same mapping as the page's playhead
for k in range(33):
    tt = ev_t(k); add(fx, tick(1.0, 3000 if k % 5 == 0 else 2400), tt, .5 if k % 5 == 0 else .3, .1)
add(fx, shutter(1), ev_t(2), .45, 0); add(fx, shutter(1), ev_t(26), .45, 0)
add(fx, thump(1.0, 42), 36.5, 1.0)
# Inquiry: teletype + verdict items
add(fx, whoosh(.25, 1), 38.52, .3)
for k in range(26): add(fx, typekey(1), 38.62 + k * .038, .35, .2 * np.sin(k))
for tt in [40.0, 40.25, 40.5, 40.75, 41.0, 41.25]: add(fx, tick(.8, 1800), tt, .35, -.2 if tt < 40.7 else .2)
add(fx, paper(1), 45.6, .35)
add(fx, thump(.6, 55), 47.6, .45)   # fact-check bar
add(fx, whoosh(.35, 1), 52.32, .3)
for i in range(5): add(fx, shutter(.7), 52.5 + i * .1, .25, -.4 + .2 * i)
fx += np.repeat(lp(brown(DUR), 400)[:N, None] * .012, 2, axis=1).astype(np.float32)   # room tone

# ── Source audio (newsreel commentary): band-pass + a little film crackle ──
def clip(path):
    x, sr = sf.read(os.path.join(D, path)); x = x if x.ndim == 1 else x.mean(1)
    if sr != SR: x = soxr.resample(x, sr, SR)
    x = bp(x, 180, 5500, 2); x = x / (np.sqrt(np.mean(x ** 2)) + 1e-9) * .09
    n = len(x); fade = int(.06 * SR); x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    crack = (np.random.rand(n) > .9993) * np.random.randn(n) * .25; x = x + lp(crack, 4000) + hp(noise(n / SR), 3000) * .004
    return x
CL = {}
for k, (at, path) in F['clips'].items(): c = clip(path); add(voc, c, at, 1.0, 0); CL[k] = (at, at + len(c) / SR)

# ── Narration ──
VO = {}
for k, at in F['vo'].items():
    x, sr = sf.read(os.path.join(D, f'audio/vo/{k}.wav')); x = x if x.ndim == 1 else x.mean(1)
    x = soxr.resample(x, sr, SR); x = x / (np.sqrt(np.mean(x[np.abs(x) > .01] ** 2)) + 1e-9) * .11
    add(voc, x, at, 1.0, 0); VO[k] = (at, at + len(x) / SR)

# ── Ducking: music −7 dB under narration, −12 dB under source audio (30 ms attack, 250 ms release)──
g = np.ones(N)
for a, b in VO.values(): g[int(a * SR):int(b * SR)] = np.minimum(g[int(a * SR):int(b * SR)], .35)
for a, b in CL.values(): g[int((a - .1) * SR):int((b + .1) * SR)] = .25
from scipy.ndimage import uniform_filter1d
g = uniform_filter1d(g, int(.25 * SR)); mus *= g[:, None]; fx *= (.5 + .5 * g)[:, None]

out = mus * 3.0 + fx * .8 + voc
# Ending: fade out 59.0–60.0
tail = int(1.0 * SR); out[-tail:] *= np.linspace(1, 0, tail)[:, None]
def tp_limit(x, ceil):  # true-peak limiter with 4× oversampling (gain only goes down, never up: take the window minimum first, then smooth), catching overshoots between samples
    from scipy.signal import resample_poly
    from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d
    up = resample_poly(x, 4, 1); n = int(.004 * SR * 4)
    g = np.minimum(1, ceil / np.maximum(maximum_filter1d(np.abs(up), 2 * n + 1), 1e-9)); g = uniform_filter1d(minimum_filter1d(g, 2 * n + 1), n)
    return resample_poly(up * g, 1, 4)[:len(x)]
out = np.stack([tp_limit(limit(out[:, c], .5), .45) for c in range(2)], 1)
os.makedirs(os.path.join(D, 'out'), exist_ok=True)
sf.write(os.path.join(D, 'out/mix.wav'), out.astype(np.float32), SR)
json.dump({'vo': VO, 'clips': CL}, open(os.path.join(D, 'out/mixlog.json'), 'w'), indent=1)
print('mix', out.shape, 'peak', float(np.abs(out).max()))

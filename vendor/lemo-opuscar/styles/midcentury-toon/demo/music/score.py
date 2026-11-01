"""《Meet Pip》 score: a 1950s West Coast cool-jazz combo (original)
vibraphone (lead) / flute (melody) / pizzicato double bass / brushed drums + ride / celesta (glockenspiel played soft + additive sine partials)
132 BPM, 4/4, 40.000 s = 22 bars, F major → G major from the climax on.
Run from the repo root: .venv/bin/python styles/midcentury-toon/demo/music/score.py
"""
import sys, os, json
sys.path.insert(0, '.')
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
from core.audio import sampler as S
from core.audio.sfx import SR, add

OUT = os.path.dirname(os.path.abspath(__file__))
S.seed(48)
rng = np.random.default_rng(48)

B = 60 / 132           # 1 beat
BAR = 4 * B
DUR = 40.0
N = int(round(DUR * SR))
SW = 0.60              # swing eighths: the off-beat lands at 60% of the beat


def T(bar, beat=0.0, swing=SW):
    """bar counts from 1, beat from 0 (fractions allowed); x.5 off-beats are swung automatically"""
    whole = np.floor(beat + 1e-9); frac = beat - whole
    if abs(frac - .5) < 1e-6: frac = swing
    return (bar - 1) * BAR + (whole + frac) * B


def M(p): return S.midi(p) if isinstance(p, str) else p


stems = {k: np.zeros((N, 2), np.float32) for k in ('drums', 'bass', 'vib', 'lead')}
hits = []
def hit(t, label): hits.append(dict(t=round(float(t), 4), label=label))
def jit(ms=6): return float(rng.uniform(-ms, ms)) / 1000


# ---------------------------------------------------------------- instrument wrappers
def bp(x, lo, hi, o=2): return sosfilt(butter(o, [lo, hi], 'band', fs=SR, output='sos'), x)
def lpf(x, f, o=2): return sosfilt(butter(o, f, 'low', fs=SR, output='sos'), x)


def motor(x, rate=5.2, depth=.32, t0=0.0):
    """vibraphone motor tremolo: amplitude modulation"""
    t = np.arange(len(x)) / SR + t0
    return x * (1 - depth * (.5 + .5 * np.sin(2 * np.pi * rate * t))).astype(np.float32)


def vib(t, pitches, dur, vel=.5, pan=-.25, hard=False, trem=0.0, gain=1.0):
    inst = 'vibraphone_hard' if hard else 'vibraphone'
    for i, p in enumerate(pitches if isinstance(pitches, (list, tuple)) else [pitches]):
        x = S.note(inst, M(p), dur, vel=vel)
        if trem: x = motor(x, depth=trem, t0=i * .013)
        add(stems['vib'], x, t, gain, pan + (i - 1.5) * .08)


def vib_run(t0, pitches, step, vel0=.35, vel1=.6, pan=-.2, ring=1.2, gain=1.0):
    """glissando / arpeggio: notes start one after another, velocity changes linearly"""
    n = len(pitches)
    for i, p in enumerate(pitches):
        v = vel0 + (vel1 - vel0) * i / max(1, n - 1)
        add(stems['vib'], S.note('vibraphone_hard', M(p), ring, vel=v), t0 + i * step, gain, pan + .5 * i / n - .25)


def flute(t, p, beats, vel=.55, stac=False, pan=.2, gain=1.0):
    if stac and M(p) >= 69:
        x = S.note('flute_stac', M(p), .2, vel=vel)
    else:
        x = S.note('flute', M(p), max(.12, beats * B * .92), vel=vel, release=.09)
    add(stems['lead'], x, t - .02, gain, pan)


def celesta(t, p, vel=.5, pan=.4, gain=1.0):
    """celesta: soft glockenspiel (bright attack) + additive sine partials (warm celesta overtones)"""
    g = S.note('glockenspiel', M(p), 2.0, vel=min(.5, vel * .7))
    f = S.hz(M(p)); d = 1.6; tt = np.arange(int(d * SR)) / SR
    s = (np.sin(2 * np.pi * f * tt) * np.exp(-tt / .55) + .35 * np.sin(2 * np.pi * 2 * f * tt) * np.exp(-tt / .18)
         + .12 * np.sin(2 * np.pi * 4.03 * f * tt) * np.exp(-tt / .05))
    s *= np.minimum(1, tt / .002)
    x = np.zeros(max(len(g), len(s)), np.float32); x[:len(g)] += g * .6; x[:len(s)] += (s * .22 * vel).astype(np.float32)
    add(stems['lead'], x, t, gain, pan)


def bass(t, p, beats=.9, vel=.6, gain=1.0):
    add(stems['bass'], S.note('jazz_bass', M(p), max(.1, beats * B), vel=vel, release=.08), t - .015, gain, 0)


def dk(t, var, vel, dur=None, pan=.3, gain=1.0):
    add(stems['drums'], S.hit('drum_kit', var, vel, dur), t, gain, pan)


def brush_tap(t, v=.5, pan=-.1):
    d = .16; tt = np.arange(int(d * SR)) / SR
    n = rng.standard_normal(len(tt))
    x = bp(n, 1500, 9000) * np.exp(-tt / .045) + .5 * bp(n, 300, 1200) * np.exp(-tt / .02)
    x += .25 * np.sin(2 * np.pi * 190 * tt) * np.exp(-tt / .03)
    add(stems['drums'], (x / 3.2 * v).astype(np.float32), t, 1, pan)


def brush_sweep(t, d, v=.3, pan=-.15, shape='arc'):
    tt = np.arange(int(d * SR)) / SR
    n = rng.standard_normal(len(tt))
    x = bp(n, 1800, 7500) + .35 * bp(n, 500, 1800)
    if shape == 'arc':
        env = np.sin(np.pi * tt / d) ** 1.5
    else:                                   # 'hit': a smear of accent, fast attack, slow release
        env = np.minimum(1, tt / .012) * np.exp(-tt / (d * .35))
    add(stems['drums'], (x * env / 4 * v).astype(np.float32), t, 1, pan)


def brushes(bar0, bar1, v=.3, taps=True, swirl=True, pedal=True):
    """brushes: left-hand circle (one per 2 beats) + taps on 2 and 4 + hi-hat pedal on 2 and 4"""
    for bar in range(bar0, bar1):
        for h in (0, 2):
            if swirl: brush_sweep(T(bar, h) + jit(4), 2 * B * 1.05, v * .8)
        for bt in (1, 3):
            if taps: brush_tap(T(bar, bt) + jit(4), v * 1.25)
            if pedal: add(stems['drums'], S.hit('hihat', 'pedal', .35 * v / .3, .3), T(bar, bt) + .004, .45, .45)


def ride(bar0, bar1, vel=.3, stick=False, eighths=False):
    for bar in range(bar0, bar1):
        pat = [0, .5, 1, 1.5, 2, 2.5, 3, 3.5] if eighths else [0, 1, 1.5, 2, 3, 3.5]
        for b in pat:
            acc = 1.0 if b in (1, 3) or (eighths and b == int(b)) else .7
            if stick: sw = .56
            else: sw = SW
            dk(T(bar, b, sw) + jit(4), 'ride_right', vel * acc, dur=1.4, pan=.35, gain=.55 if not stick else .6)


# ---------------------------------------------------------------- harmony (vibraphone voicings / bass roots)
V = {
    'F6':   ['A3', 'C4', 'D4', 'F4'],
    'F69':  ['F3', 'A3', 'D4', 'G4', 'C5'],
    'Dm9':  ['F3', 'A3', 'C4', 'E4'],
    'G13':  ['F3', 'B3', 'E4'],
    'Gm7':  ['F3', 'Bb3', 'D4'],
    'C13':  ['Bb3', 'E4', 'A4'],
    'Bbmaj7': ['Bb3', 'D4', 'F4', 'A4'],
    'Am7':  ['G3', 'C4', 'E4'],
    'C6':   ['E4', 'G4', 'A4', 'C5'],
    'Bbm6': ['Db4', 'F4', 'G4', 'Bb4'],
    'C9':   ['Bb3', 'D4', 'E4', 'G4'],
    # G major
    'G69':  ['G3', 'B3', 'E4', 'A4', 'D5'],
    'G6':   ['B3', 'D4', 'E4', 'G4'],
    'Em9':  ['G3', 'B3', 'D4', 'F#4'],
    'A13':  ['G3', 'C#4', 'F#4'],
    'Am7g': ['G3', 'C4', 'E4'],
    'D13':  ['F#3', 'C4', 'E4', 'B4'],
    'Cmaj7': ['C4', 'E4', 'G4', 'B4'],
    'D9':   ['F#3', 'C4', 'E4', 'A4'],
    'Gmaj7': ['F#3', 'B3', 'D4', 'G4'],
}


def comp(bar, chord, vel=.32, charleston=True, second=None):
    """vibraphone comping: long on beat 1 + short on the off-beat of beat 2 (Charleston)"""
    vib(T(bar, 0) + jit(3), V[chord], 1.4 * B, vel)
    if charleston: vib(T(bar, 1.5) + jit(3), V[second or chord], .6 * B, vel * .8)


# ================================================================ hook A 0–1.364: complete silence
# ================================================================ hook B 1.364: rising vibraphone glissando + suspended-cymbal swell
g0 = T(1, 3)
hit(g0, 'hookB: vib gliss up + sus cymbal swell')
gl = ['C4', 'D4', 'F4', 'G4', 'A4', 'C5', 'D5', 'F5', 'G5', 'A5', 'C6']
vib_run(g0, gl, (T(2, 0) - g0 - .03) / len(gl), .25, .6, ring=1.0)
cr = S.hit('sus_cymbal', 'roll', .6)
seg = int((T(2, 0) - g0) * SR); cr = cr[:seg] * np.linspace(0, 1, seg) ** 2.2
add(stems['drums'], cr.astype(np.float32), g0, .9, .25)

# ================================================================ 1.818 full band ta-da F6/9
t = T(2, 0); hit(t, 'TA-DA full band F6/9')
vib(t, V['F69'], 2.2 * B, .72, hard=True, trem=.3)
vib(t, ['A5'], 2.2 * B, .5, hard=True)
bass(t, 'F1', 1.8, .85)
flute(t, 'A5', .5, .6, stac=True)
celesta(t, 'F6', .7)
dk(t, 'crash_right', .55, dur=2.6, pan=.35, gain=.6)
dk(t, 'kick_drum_left', .45, pan=0, gain=.6)
brush_tap(t, .8)

# ---------------- theme A (bars 2–4 + landing in bar 5), F major (original)
THEME_A = [  # (bar offset, beat, note, length in beats, stac)
    (0, 1.0, 'A4', .5, 0), (0, 1.5, 'C5', .5, 0), (0, 2.0, 'F5', 1.0, 0), (0, 3.0, 'E5', .5, 1), (0, 3.5, 'D5', .5, 0),
    (1, 0.0, 'C5', 1.5, 0), (1, 1.5, 'A4', .5, 0), (1, 2.0, 'B4', .5, 1), (1, 2.5, 'D5', .5, 0), (1, 3.0, 'G5', 1.0, 0),
    (2, 0.0, 'F5', .5, 1), (2, 0.5, 'D5', .5, 0), (2, 1.0, 'Bb4', 1.0, 0), (2, 2.5, 'E5', .5, 0), (2, 3.0, 'G5', .5, 1), (2, 3.5, 'Bb5', .5, 0),
    (3, 0.0, 'A5', 2.0, 0),
]
for bo, bt, p, ln, st in THEME_A:
    t = T(2 + bo, bt)
    if bo == 0 and bt == 1.0: continue          # the first beat after the ta-da is left for the narration's opening line; the theme starts on the off-beat of beat 2
    in_vo = 1.98 < t < 4.3
    flute(t + jit(4), p, ln, .40 if in_vo else .52, stac=bool(st))
# narration 1.98–4.3: vibraphone only on beat 1, walking bass
comp(3, 'Dm9', .24, charleston=False); vib(T(3, 2), V['G13'], 1.2 * B, .22)
comp(4, 'Gm7', .28, second='Gm7'); vib(T(4, 2), V['C13'], 1.2 * B, .28)
t = T(2, 2); hit(t, 'woodblock'); add(stems['drums'], S.hit('woodblock', 'b', .55), t, .8, -.35)
t = T(3, 0); hit(t, 'brush swipe accent'); brush_sweep(t, .55, 1.0, shape='hit'); brush_tap(t, 1.0)
dk(t, 'kick_drum_left', .3, pan=0, gain=.5)
brushes(2, 5, .3)
ride(2, 5, .22)

WALK = {  # 4 quarter notes per bar
    2: ['F2', 'A2', 'C3', 'C#3'], 3: ['D3', 'A2', 'G2', 'B2'], 4: ['G2', 'D2', 'C2', 'E2'],
    5: ['F2', 'A2', 'C3', 'D3'], 6: ['D3', 'C3', 'B2', 'G2'], 7: ['G2', 'Bb2', 'C3', 'A2'],
    8: ['Bb2', 'D3', 'F2', 'G#2'], 9: ['A2', 'E2', 'C2', 'F#2'], 10: ['G2', 'D2', 'Bb1', 'B1'],
}
for bar, ns in WALK.items():
    for i, p in enumerate(ns):
        if bar == 2 and i == 0: continue       # ta-da already placed
        bass(T(bar, i) + jit(4), p, .88, .62 if i == 0 else .55)

# ================================================================ step 1 7.273: vibraphone F6
t = T(5, 0); hit(t, 'STEP 1 chord vib F6')
vib(t, V['F6'] + ['A4'], 3.0 * B, .62, trem=.28)
# theme A' (light): the flute takes it up high, the vibraphone answers in the gaps
A2 = [
    (0, 2.5, 'G5', .5, 0), (0, 3.0, 'F5', .5, 1), (0, 3.5, 'D5', .5, 0),
    (1, 0.0, 'C5', 1.0, 0), (1, 1.5, 'D5', .5, 0), (1, 2.0, 'F5', .5, 1), (1, 2.5, 'A5', 1.5, 0),
    (2, 0.0, 'G5', 1.5, 0), (2, 2.0, 'E5', .5, 1), (2, 2.5, 'C5', .5, 0), (2, 3.0, 'Bb4', .5, 0), (2, 3.5, 'C5', .5, 0),
]
for bo, bt, p, ln, st in A2:
    flute(T(5 + bo, bt) + jit(4), p, ln, .42, stac=bool(st))
comp(6, 'Dm9', .26, second='Dm9'); vib(T(6, 2), V['G13'], 1.2 * B, .24)
comp(7, 'Gm7', .26, second='Gm7'); vib(T(7, 2), V['C13'], 1.2 * B, .26)
vib_run(T(7, 3.5), ['C5', 'D5', 'E5'], B / 4, .22, .3, ring=.8)          # a small answering phrase pushing into step 2
brushes(5, 8, .22, pedal=True)
ride(6, 8, .16)

# ================================================================ step 2 12.727: vibraphone B♭maj7, theme B (rising question)
t = T(8, 0); hit(t, 'STEP 2 chord vib Bbmaj7')
vib(t, V['Bbmaj7'] + ['D5'], 3.0 * B, .62, trem=.28)
dk(t, 'kick_drum_left', .25, pan=0, gain=.45)
THEME_B = [
    (0, 0.5, 'D5', .5, 0), (0, 1.0, 'F5', .5, 1), (0, 1.5, 'A5', 1.0, 0), (0, 2.5, 'G5', .5, 0), (0, 3.0, 'F5', .5, 1), (0, 3.5, 'A5', .5, 0),
    (1, 0.0, 'C6', 1.5, 0), (1, 1.5, 'B5', .5, 0),
    (2, 0.5, 'D5', .5, 0), (2, 1.0, 'E5', .5, 1), (2, 1.5, 'G5', .5, 0), (2, 2.0, 'Bb5', 1.0, 0), (2, 3.0, 'C6', .5, 1), (2, 3.5, 'D6', 2.2, 0),
]
for bo, bt, p, ln, st in THEME_B:
    flute(T(8 + bo, bt) + jit(4), p, ln, .5, stac=bool(st))
comp(9, 'Am7', .28, charleston=False); vib(T(9, 2), V['C6'], 1.0 * B, .22)
comp(10, 'Gm7', .28, charleston=False); vib(T(10, 2), V['Bbm6'], 1.6 * B, .3)
# Wi-Fi three chimes: celesta stepping upward
for tt, p in ((15.4545, 'C6'), (15.9091, 'E6'), (16.3636, 'G6')):
    hit(tt, f'celesta wifi {p}'); celesta(tt, p, .6)
brushes(8, 11, .28)
ride(8, 11, .24)
add(stems['drums'], S.hit('snare2', 'taps', .25, .5), T(10, 3.5), .5, -.1)

# ================================================================ step 3 18.182: vibraphone C9, bass climbs chromatically, only the ride left
t = T(11, 0); hit(t, 'STEP 3 chord vib C9')
vib(t, V['C9'], 4.0 * B, .72, trem=.3)
for i, p in enumerate(['C2', 'C#2', 'D2', 'D#2', 'E2']):
    bass(T(11 + i // 4, i % 4), p, .7, .5 + .05 * i)
for b in [0, 1, 1.5, 2, 3, 3.5]:
    dk(T(11, b), 'ride_right', .24 if b in (1, 3) else .17, dur=.6, pan=.35, gain=.5)
for b in [0, 1, 1.5]:
    dk(T(12, b), 'ride_right', .22 if b == 1 else .16, dur=.45, pan=.35, gain=.5)
t = T(12, 1); hit(t, 'key press: light vib single F#5')
vib(t, 'F#5', .5, .22)

# ================================================================ silence B 20.909–21.818 (guaranteed by the mask)
# ================================================================ climax 21.818: G major forte, double time
t = T(13, 0); hit(t, 'CLIMAX full band G6/9 (key up a tone, double-time)')
vib(t, V['G69'], 2.0 * B, .8, hard=True, trem=.3); vib(t, ['B5'], 2.0 * B, .55, hard=True)
bass(t, 'G1', 1.0, .9)
dk(t, 'crash_right', .75, dur=3.0, pan=.35, gain=.7)
dk(t, 'kick_drum_left', .6, pan=0, gain=.7)
celesta(t, 'D6', .6)
# flute theme A an octave up (+14 semitones = up a whole tone plus an octave); bar 3 rewritten to land on the accent at 26.818
CLIMAX = [(bo, bt, S.midi(p) + 14, ln, st) for bo, bt, p, ln, st in THEME_A if bo < 2]
CLIMAX += [(2, 0.0, 'G6', .5, 1), (2, 0.5, 'E6', .5, 0), (2, 1.0, 'C6', 1.0, 0), (2, 2.5, 'F#6', .5, 0), (2, 3.0, 'A6', 1.0, 0)]
for bo, bt, p, ln, st in CLIMAX:
    flute(T(13 + bo, bt, .56) + jit(3), p, ln, .62, stac=bool(st))
# comping
comp(13, 'G69', .36, second='G6')
vib(T(14, 0), V['Em9'], .9 * B, .34); vib(T(14, 2), V['A13'], .9 * B, .34)
vib(T(15, 0), V['Am7g'], .9 * B, .34); vib(T(15, 2), V['D13'], .6 * B, .3)
# three rising arpeggios (living room / hallway / kitchen), each higher than the last
ARPS = [(T(14, 0), ['E4', 'G4', 'B4', 'D5', 'E5', 'G5'], 'arp1 living room'),
        (T(14, 2), ['A4', 'C#5', 'E5', 'G5', 'A5', 'C#6'], 'arp2 hallway'),
        (T(15, 0), ['C5', 'E5', 'G5', 'A5', 'C6', 'E6'], 'arp3 kitchen')]
for i, (t, ps, lab) in enumerate(ARPS):
    hit(t, lab); vib_run(t, ps, B / 4, .45 + .08 * i, .7 + .08 * i, pan=-.3, ring=1.1)
# 26.818 accent + celesta ding (back on the charging dock)
t = T(15, 3); hit(t, 'accent chord D13 + celesta ding (dock)')
vib(t, V['D13'], 1.0 * B, .75, hard=True)
celesta(t, 'A6', .8); celesta(t + .003, 'D6', .45)
dk(t, 'crash_right', .5, dur=2.0, pan=.4, gain=.55); dk(t, 'snare_2', .55, pan=.05, gain=.55); dk(t, 'kick_drum_left', .55, pan=0, gain=.6)
bass(t, 'D2', 1.0, .8)
# glissando tail runs past 27.273 (L-cut)
gl2 = ['D5', 'E5', 'G5', 'A5', 'B5', 'D6', 'E6']
vib_run(T(15, 3.5, .5) + .03, gl2, .052, .45, .3, pan=-.1, ring=1.6)
hit(T(15, 3.5, .5) + .03, 'vib gliss tail (L-cut into tips)')
# bass eighth notes (double time)
def eighths(bar, half, root, fifth, nxt):
    r, f = M(root), M(fifth)
    for i, p in enumerate([r, r + 12, f, M(nxt) - 1]):
        bass(T(bar, half + i * .5, .56) + jit(3), p, .45, .62 if i == 0 else .5)
for bar, half, r, f, nx in [(13, 0, 'G2', 'D3', 'G2'), (13, 2, 'G2', 'D3', 'E2'), (14, 0, 'E2', 'B2', 'A2'),
                            (14, 2, 'A2', 'E2', 'A2'), (15, 0, 'A2', 'E2', 'D2')]:
    if (bar, half) == (13, 0):
        for i, p in enumerate([None, M('G2'), M('D3'), M('G2') - 1]):
            if p: bass(T(13, i * .5, .56), p, .45, .5)
    else:
        eighths(bar, half, r, f, nx)
for i, p in enumerate(['D2', 'A2']): bass(T(15, 2 + i * .5, .56), p, .45, .55)
bass(T(15, 3.5, .56), 'F#2', .45, .5)
# drums: ride eighths with sticks, snare on 2/4, hi-hat pedal, kick
ride(13, 16, .5, stick=True, eighths=True)
for bar in (13, 14, 15):
    for bt in (1, 3):
        if (bar, bt) == (15, 3): continue
        dk(T(bar, bt) + jit(3), 'snare_2', .38, pan=.05, gain=.45)
        add(stems['drums'], S.hit('hihat', 'pedal', .5, .3), T(bar, bt), .45, .45)
    for bt in (0, 2):
        if (bar, bt) != (13, 0): dk(T(bar, bt), 'kick_drum_left', .3, pan=0, gain=.45)
    dk(T(bar, 2.5, .56), 'snare_2', .18, pan=.05, gain=.4)

# ================================================================ tip 27.273–30.2: half-time feel (solo flute phrase + bass + woodblock)
t = T(16, 0); hit(t, 'TIPS half-time: flute solo + bass + woodblock')
for tt, p, ln in [(T(16, 0), 'G2', 1.9), (T(16, 2), 'E2', 1.9), (T(17, 0), 'C2', 1.0), (T(17, 1), 'D2', 1.5)]:
    bass(tt, p, ln, .55)
for tt, v in [(T(16, 0), 'b'), (T(16, 2), 'c'), (T(17, 0), 'b')]:
    add(stems['drums'], S.hit('woodblock', v, .4), tt, .6, -.35)
for tt, p, ln, v in [(T(16, 1), 'D5', 1.4, .34), (T(16, 2.5), 'E5', .5, .3), (T(16, 3), 'G5', 1.5, .34),
                     (T(17, .5), 'F#5', .5, .3), (T(17, 1), 'D5', 1.6, .3)]:
    flute(tt, p, ln, v)
vib(T(16, 0), V['Gmaj7'], 2 * B, .16); vib(T(17, 0), V['Cmaj7'], 2 * B, .14)

# ================================================================ near-silence C 30.2–30.909 (mask)
# ================================================================ end slate: the three step chords return on the beat (G6 / Cmaj7 / D9)
for i, (bt, ch, bp_) in enumerate([(0, 'G6', 'G2'), (1, 'Cmaj7', 'C3'), (2, 'D9', 'D2')]):
    t = T(18, bt); hit(t, f'recap step {i + 1} {ch}')
    vib(t, V[ch], .42 * B, .62, hard=True); bass(t, bp_, .4, .75)
# 32.273 full band, closing phrase of theme A (G major)
t = T(18, 3); hit(t, 'full band closing phrase (G)')
CLOSE = [(18, 3.0, 'B4', .5, 0), (18, 3.5, 'D5', .5, 0),
         (19, 0.0, 'G5', 1.0, 0), (19, 1.0, 'F#5', .5, 1), (19, 1.5, 'E5', .5, 0), (19, 2.0, 'D5', .5, 1), (19, 2.5, 'C5', .5, 0),
         (19, 3.0, 'D5', .5, 1), (19, 3.5, 'F#5', .5, 0), (20, 0.0, 'A5', 3.6, 0)]
for bar, bt, p, ln, st in CLOSE:
    flute(T(bar, bt) + (0 if (bar, bt) == (20, 0) else jit(3)), p, ln, .45 if bar < 20 else .5, stac=bool(st))
for i, p in enumerate(['G#2']): bass(T(18, 3), p, .88, .55)
for i, p in enumerate(['A2', 'E2', 'D2', 'F#2']): bass(T(19, i) + jit(3), p, .88, .55)
comp(19, 'Am7g', .26, charleston=False); vib(T(19, 2), V['D13'], 1.2 * B, .26)
brushes(19, 20, .26); brush_tap(T(18, 3), .5)
ride(19, 20, .2)
# 34.545 final chord G6/9: vibraphone tremolo sustain
t = T(20, 0); hit(t, 'final chord G6/9 (vib tremolo)')
vib(t, V['G69'], 4 * B, .6, trem=.4)
bass(t, 'G1', 3.5, .7)
add(stems['drums'], S.hit('sus_cymbal', 'hit', .35), t, .5, .3)
dk(t, 'kick_drum_left', .3, pan=0, gain=.45)
# tremolo: soft-mallet roll (two strokes per beat, getting softer)
for k in range(1, 7):
    vib(t + k * B / 2, ['B4', 'E5'], .5 * B, .2 - .02 * k, trem=.4, gain=.7)

# ================================================================ end card 36.364: button
t = T(21, 0); hit(t, 'BUTTON bass + celesta ding')
bass(t, 'G1', .5, .9); celesta(t, 'G6', .75); celesta(t + .002, 'D6', .35)
brush_tap(t, .7); dk(t, 'kick_drum_left', .35, pan=0, gain=.5)
vib(t, ['B3', 'D4', 'E4', 'A4', 'G4'], 3.6, .34, trem=.35)
hit(39.5, 'fade to silence 39.5–40.0')

# ---------------------------------------------------------------- reverb, silence mask, bus
ROOM = dict(drums=(.3, .1), bass=(.22, .06), vib=(.45, .2), lead=(.4, .18))
GAIN = dict(drums=.9, bass=1.05, vib=.95, lead=.85)
for k in stems:
    stems[k] = S.room(stems[k] * GAIN[k], size=ROOM[k][0], mix=ROOM[k][1]).astype(np.float32)

tt = np.arange(N) / SR
mask = np.ones(N)
def cos_fade(a, b):  # falls from 1 to 0 over a→b
    s = (tt >= a) & (tt < b); mask[s] *= .5 + .5 * np.cos(np.pi * (tt[s] - a) / (b - a))
mask[tt < 1.364] = 0
cos_fade(20.70, 20.895); mask[(tt >= 20.895) & (tt < 21.818)] = 0
cos_fade(29.98, 30.19); mask[(tt >= 30.19) & (tt < 30.909)] = 0
cos_fade(39.5, 40.0)
for k in stems: stems[k] *= mask[:, None].astype(np.float32)

mix = sum(stems.values())
# bus limiting: compute one gain curve and apply it to the stems too (stems summed = final mix)
from scipy.ndimage import maximum_filter1d, uniform_filter1d
ceil = 10 ** (-1.3 / 20)
pk = np.abs(mix).max(axis=1)
target = pk.max()
pre = min(1.0, .98 / max(np.percentile(pk[pk > 0], 99.9), 1e-9))   # first raise the whole thing to a suitable level
pk *= pre
n = int(.005 * SR)
g = np.minimum(1, ceil / np.maximum(maximum_filter1d(pk, 2 * n + 1), 1e-9))
g = uniform_filter1d(g, n) * pre
g = np.minimum(g, ceil / np.maximum(np.abs(mix).max(axis=1), 1e-9))
print('limiter min gain dB', 20 * np.log10(g.min()), 'pct<-3dB', (g < .708).mean())
for k in stems: stems[k] *= g[:, None].astype(np.float32)
mix = sum(stems.values())

os.makedirs(f'{OUT}/stems', exist_ok=True)
sf.write(f'{OUT}/score.wav', mix.astype(np.float32), SR, subtype='PCM_24')
for k, x in stems.items():
    sf.write(f'{OUT}/stems/{k}.wav', x.astype(np.float32), SR, subtype='PCM_24')
hits.sort(key=lambda h: h['t'])
json.dump(dict(bpm=132, beat=B, bar=BAR, duration=DUR, silences=[[0, 1.364], [20.909, 21.818], [30.2, 30.909]], hits=hits),
          open(f'{OUT}/hits.json', 'w'), ensure_ascii=False, indent=1)
used = ['vibraphone', 'vibraphone_hard', 'flute', 'flute_stac', 'jazz_bass', 'drum_kit', 'hihat', 'sus_cymbal',
        'woodblock', 'snare2', 'glockenspiel']
open(f'{OUT}/CREDITS_music.txt', 'w').write(
    'Music: "Meet Pip" — original score, generated in code (midcentury-toon demo)\n' + '\n'.join(S.credits(used)) + '\n')
print('done', mix.shape, 'peak dBFS', 20 * np.log10(np.abs(mix).max()))

"""Toy Town Rush Hour — original score (sampled-marimba minimalism, event-driven)
Run: .venv/bin/python styles/tilt-shift/demo/music/score.py
Input ../events.json; output score.wav (48k stereo), stems/*.wav, cues.json, CREDITS.txt

Design: 120 BPM, sixteenth = 0.125s. Tonal centre D (D Lydian D E F# G# A B C#, drifting with D major pentatonic).
- Fixed skeleton: marimba A loops a 12-step theme over 16-step bars (a built-in 3:4 offset); each cell of the skeleton
  sounds only when "there is a matching event within ±60ms of that cell" or the "section's base fill rate" hits → the busier the city, the fuller the phrase.
- Marimba B: same skeleton, enters from the train section; in the big-jam section it shifts one sixteenth later each bar (phasing).
- Bass marimba + pizzicato double bass: train cars = bass notes; afterwards they serve as the root.
- Glockenspiel/vibraphone = pedestrians; woodblock = traffic lights; brass staccato = "tuned-horn" (调音喇叭) eighth-note pulsing chords.
"""
import sys, os, json
import numpy as np, soundfile as sf
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, ROOT)
from core.audio import sampler as S
from core.audio.sfx import SR, add, limit

HERE = os.path.dirname(os.path.abspath(__file__))
EV = json.load(open(os.path.join(HERE, '..', 'events.json')))['ev']
DUR = 38.0
STEP = .125
S.seed(20260925)
rng = np.random.default_rng(7)
N = int(DUR * SR) + SR
stems = {k: np.zeros((N, 2), np.float32) for k in ['marA', 'marB', 'bass', 'glock', 'perc', 'brass', 'pad']}
used = set()

_cache = {}
def note(inst, p, dur, vel, release=None, attack=0.0):
    key = (inst, p, round(dur, 3), round(vel, 2), release, attack)
    if key not in _cache:
        _cache[key] = S.note(inst, p, dur, vel, release=release, attack=attack)
    used.add(inst)
    return _cache[key]

def put(stem, inst, p, t, dur=.6, vel=.7, pan=0., gain=1., release=None, attack=0.):
    if t < 0 or t > DUR: return
    add(stems[stem], note(inst, p, dur, vel, release, attack), t, gain, pan)

def ev(ty, win=None):
    return sorted(e['t'] for e in EV if e['type'] == ty and (win is None or e.get('win') == win))

def near(ts, t, w=.06):
    i = np.searchsorted(ts, t - w)
    return i < len(ts) and ts[i] <= t + w

# —— Theme and harmony ——
FIRST = 'A5'                       # the first note at 3.0 = the top note of the final chord
# Marimba A 12-step skeleton (None = rest)
SKEL = ['D5', 'A4', 'E5', 'F#5', None, 'A4', 'C#5', 'E5', 'A5', None, 'F#5', 'E5']
# The title's 15 letters = the theme's 15 notes: TOY / TOWN / RUSH / HOUR (ending on A5)
TITLE = ['D5', 'F#5', 'A5', 'D5', 'F#5', 'E5', 'C#5', 'B4', 'D5', 'E5', 'F#5', 'E5', 'F#5', 'G#5', 'A5']
# Harmony (changes every 2 bars = 4s): root + chord tones (for brass/bass/glockenspiel)
CH = {
    'D':  ('D3', ['D4', 'F#4', 'A4', 'C#5', 'E5']),
    'Bm': ('B2', ['D4', 'F#4', 'A4', 'B4', 'E5']),
    'E/D': ('D3', ['E4', 'G#4', 'B4', 'D5', 'F#5']),     # Lydian II/I: the tension of the jam
    'F#m': ('F#2', ['C#4', 'E4', 'F#4', 'A4', 'C#5']),
}
def chord_at(t):
    if t < 14: return 'D'
    if t < 16: return 'Bm'
    if t < 19: return 'D'
    if t < 20: return 'Bm'
    if t < 22: return 'E/D'
    if t < 24: return 'F#m'
    if t < 32: return 'D'
    if t < 34: return 'Bm'
    return 'D'

# ============ 0–5 Dawn: almost silent, only "the first note" and "the second note" ============
put('marA', 'marimba', FIRST, 3.0, 2.5, .62, -.1, 1.1)
put('marA', 'marimba', 'E5', 4.5, 2.0, .5, .2, .9)
put('pad', 'vibraphone_bowed', 'A4', 3.0, 3.5, .35, -.2, .35, release=1.5, attack=.6)

# ============ 5–9 Title: 15 letters = the theme's 15 notes; sunrise drone ============
for i, t in enumerate(ev('letter')):
    put('marA', 'marimba', TITLE[i], t, .9, .62 + .02 * (i % 3), -.25 + .5 * (i / 14), .8)
    if i in (2, 6, 10, 14):   # a supporting note an octave lower at the end of each word
        put('bass', 'marimba', S.name(S.midi(TITLE[i]) - 12), t, 1.0, .45, 0, .6)
put('pad', 'vibraphone_bowed', 'D4', 5.8, 3.4, .32, -.3, .4, release=1.2, attack=1.2)
put('pad', 'vibraphone_bowed', 'A4', 6.4, 2.8, .30, .3, .35, release=1.2, attack=1.2)

# ============ 9–19 Junction + train: skeleton + event gating ============
cars_ix = np.array(ev('car', 'ix')); cars_tr = np.array(ev('car', 'train'))
lights = np.array(ev('light', 'ix') + ev('light', 'train')); peds = ev('ped', 'ix') + ev('ped', 'train')
def fill_rate(t):
    if t < 9: return 0
    if t < 14: return .3 + .2 * (t - 9) / 5            # junction: about 35–40%, gradually filling
    if t < 19: return .5 + .2 * (t - 14) / 5           # train: about 60%
    return 1.0
gate_log = []
for k in range(int(9 / STEP), int(19 / STEP)):
    t = k * STEP
    p = SKEL[k % 12]
    carHit = near(cars_ix, t) or near(cars_tr, t)
    base = rng.random() < fill_rate(t)
    if p and (carHit or base):
        acc = 1.0 if (k % 4 == 0) else .85
        put('marA', 'marimba', p, t, .5, (.58 + (.12 if carHit else 0)) * acc, -.3, 1.1)
        gate_log.append((round(t, 3), 'car' if carHit else 'fill'))
    # Traffic-light pulse: eighth-note woodblock, accent + claves on the light change
    if k % 2 == 0:
        acc = near(lights, t, .07)
        add(stems['perc'], S.hit('woodblock', 'b' if acc else 'a', .75 if acc else .36), t, .9 if acc else .55, -.05)
        used.add('woodblock')
        if acc: add(stems['perc'], S.hit('claves', None, .6), t, .5, .15); used.add('claves')
    # Bar downbeat: bass-marimba root
    if k % 16 == 0 and t < 14:
        root = CH[chord_at(t)][0]
        put('bass', 'marimba', S.name(S.midi(root) + 12), t, 1.6, .5, 0, .8)
# Pedestrians = triplet glints on glockenspiel / vibraphone
for t in peds:
    if 9 <= t < 19:
        for j, q in enumerate(['A5', 'C#6', 'E6']):
            put('glock', 'glockenspiel', q, t + j * STEP / 2, .8, .45 - .06 * j, .35, .55)
        put('glock', 'vibraphone', 'E5', t, 1.5, .4, .4, .5)
# Marimba B: enters at 16.0 (same skeleton, a voice a third higher, fill rate follows)
for k in range(int(16 / STEP), int(19 / STEP)):
    t = k * STEP; p = SKEL[(k + 3) % 12]
    if p and rng.random() < .55:
        put('marB', 'marimba', S.name(S.midi(p) + 4 if p[0] in 'DA' else S.midi(p) + 3), t, .5, .5, .35, .8)

# Train: 6 cars = bass marimba + pizzicato double bass (eighths → quarters → halves, finally at rest)
BASSLINE = ['D3', 'D3', 'A2', 'A2', 'B2', 'D3']
for i, t in enumerate(ev('carriage')):
    put('bass', 'marimba', BASSLINE[i], t, 1.4, .8, 0, 1.1)
    put('bass', 'contrabass_pizz', BASSLINE[i], t, 1.2, .7, 0, .6)
# After it stops: sustained quarter-note root
for t in np.arange(17.5, 19.0, .5):
    put('bass', 'marimba', 'D3', t, .9, .55, 0, .75)

# ============ 19–22.5 Big jam: skeleton completely full, phasing, brass pulsing chords ============
def jam_bar(t0, t1, out_offset=0.0, stems_=stems):
    """Write the jam-section music into stems_ (reused by the normal section and the "tape slowdown" section)"""
    for k in range(int(round(t0 / STEP)), int(round(t1 / STEP))):
        t = k * STEP
        bar = int((t - 19) // 2)
        pA = SKEL[k % 12]
        if pA: add(stems_['marA'], note('marimba', pA, .45, .72 if k % 4 == 0 else .6), t + out_offset, .95, -.35)
        pB = SKEL[(k - bar) % 12]                                   # shifted one sixteenth later each bar (phasing)
        if pB: add(stems_['marB'], note('marimba', S.name(S.midi(pB) + 12) if pB in ('A4', 'C#5') else pB, .45, .55), t + out_offset, .75, .4)
        root, tones = CH[chord_at(t)]
        if k % 2 == 0:   # bass eighths
            add(stems_['bass'], note('marimba', S.name(S.midi(root) + 12) if S.midi(root) < 41 else root, .4, .7), t + out_offset, .9, 0)
        if k % 4 == 2:   # brass "tuned horns": eighth-note pulsing chords on the offbeats
            acc = 1.0
            for j, q in enumerate(tones[:3]):
                inst = ['trombone_stac', 'horn_stac', 'trumpet_stac'][j]
                add(stems_['brass'], note(inst, q, .22, .55 * acc), t + out_offset, .55, [-.3, .05, .35][j])
        if k % 2 == 0:
            add(stems_['perc'], S.hit('woodblock', 'a', .35), t + out_offset, .4, -.05)
        if k % 8 == 4: add(stems_['perc'], S.hit('shaker', 'down', .4), t + out_offset, .35, .3); used.add('shaker')
# Normal section
jam_bar(19.0, 22.5)
# Horn accents (20.0, 22.0): loud brass chords + timpani-mallet bass
for t in ev('hornChord'):
    root, tones = CH[chord_at(t)]
    for j, q in enumerate(tones):
        inst = ['trombone', 'horn', 'horn', 'trumpet', 'trumpet'][j]
        put('brass', inst, q, t, .55, .7, [-.4, -.15, .1, .3, .45][j], .45, release=.25)
    put('bass', 'marimba', 'D3' if t < 21 else 'F#2', t, 1.2, .85, 0, 1.0)
    add(stems['perc'], S.hit('sus_cymbal', 'stick', .5), t, .35, .2); used.add('sus_cymbal')
# Glockenspiel glints on every beat in the jam section (the crowd weaving between the cars)
for t in np.arange(19.0, 22.5, .5):
    put('glock', 'glockenspiel', ['E6', 'C#6', 'A5', 'B5'][int(t * 2) % 4], t + .25, .5, .32, .4, .45)

# ============ 22.5–24.0 "Tape slowdown": keep writing the jam music to 25s, then slow it down with varispeed ============
tape = {k: np.zeros((N, 2), np.float32) for k in stems}
jam_bar(22.5, 25.5, 0.0, tape)
def tape_stop(x, t0, t1):
    """From t0 the playback speed eases from 1 down to ~0.25, reaching zero at t1; pitch slides down with it"""
    a, b = int(t0 * SR), int(t1 * SR)
    n = b - a; u = np.arange(n) / n
    rate = 1 - .78 * u ** 1.3
    pos = a + np.cumsum(rate)
    out = np.zeros_like(x)
    for c in range(2):
        out[a:b, c] = np.interp(pos, np.arange(len(x)), x[:, c])
    fade = (1 - u) ** 1.5
    out[a:b] *= fade[:, None]
    return out
for k, drop in [('marA', 1.0), ('marB', .55), ('bass', .8), ('brass', .35), ('perc', .45), ('glock', .25), ('pad', 1.0)]:
    y = tape_stop(tape[k], 22.5, 24.0)
    # Voices drop out one by one: the smaller drop is, the earlier it fades
    a, b = int(22.5 * SR), int(24.0 * SR); u = np.arange(b - a) / (b - a)
    y[a:b] *= np.clip((drop - u) / max(drop, .01) * 1.6, 0, 1)[:, None]
    stems[k] += y

# ============ 24–30 Rest: only the light notes for the kerb hops ============
HOP_P = ['F#5', 'A5', 'B5', 'C#6']
for i, t in enumerate(ev('hop')[:4]):
    put('glock', 'vibraphone', HOP_P[i], t, 2.2, .42, -.1 + .1 * i, .7)
    put('glock', 'glockenspiel', S.name(S.midi(HOP_P[i]) + 12), t, 1.2, .22, .2, .3)
tf = ev('hopFail')[0]
add(stems['perc'], S.hit('woodblock', 'c', .45), tf, .5, .1)
put('marA', 'marimba', 'A4', tf + .02, .25, .35, .1, .6)
t_ok = ev('hop')[4]
put('glock', 'vibraphone', 'D6', t_ok, 2.5, .5, .15, .8)
put('glock', 'glockenspiel', 'D6', t_ok, 1.5, .32, .25, .45)
put('glock', 'glockenspiel', 'A6', t_ok + .12, 1.2, .2, .3, .3)

# ============ 30–34 Da capo: everyone returns, the theme once in full ============
t0 = 30.0
root, tones = CH['D']
for j, q in enumerate(tones):
    put('brass', ['trombone', 'horn', 'horn', 'trumpet', 'trumpet'][j], q, t0, .7, .72, [-.4, -.15, .1, .3, .45][j], .5, release=.35)
put('bass', 'marimba', 'D3', t0, 1.5, .9, 0, 1.1); put('bass', 'contrabass_pizz', 'D2', t0, 1.5, .8, 0, .7)
add(stems['perc'], S.hit('sus_cymbal', 'stick', .6), t0, .45, .25)
# Theme (the title's 15 notes) as an eighth-note melody, 30.0–33.5
for i, p in enumerate(TITLE):
    put('marB', 'marimba', p, t0 + i * .25, .8, .7, .3, .85)
# Marimba A skeleton, sixteenths completely full (register lowered a little to leave room for the narration)
for k in range(int(30 / STEP), int(33.75 / STEP)):
    t = k * STEP; p = SKEL[k % 12]
    vo = 30.6 <= t < 32.3
    if p: put('marA', 'marimba', p, t, .45, (.55 if vo else .66) * (1 if k % 4 == 0 else .88), -.35, .8 if vo else .95)
    if k % 2 == 0:
        r = CH[chord_at(t)][0]
        put('bass', 'marimba', S.name(S.midi(r) + 12) if S.midi(r) < 41 else r, t, .4, .65, 0, .8)
        add(stems['perc'], S.hit('woodblock', 'a', .3), t, .35, -.05)
    if k % 4 == 2 and not vo:
        for j, q in enumerate(CH[chord_at(t)][1][:3]):
            put('brass', ['trombone_stac', 'horn_stac', 'trumpet_stac'][j], q, t, .2, .48, [-.3, .05, .35][j], .45)
for t in np.arange(30.25, 33.75, .5):
    put('glock', 'glockenspiel', ['A5', 'E6', 'C#6', 'F#6'][int(t * 2) % 4], t, .5, .3, .4, .4)

# ============ 34–38 Final chord: marimba roll + vibraphone + long brass notes, top note = the first note A5 ============
tc = 34.0
FINAL = ['D3', 'A3', 'F#4', 'C#5', 'E5', FIRST]
for j, p in enumerate(FINAL):
    put('glock', 'vibraphone_hard' if j > 1 else 'marimba', p, tc, 4.0, .6, -.3 + .12 * j, .7, release=2.5)
    # Roll: thirty-second repeats of the sixteenths, decrescendo
    for r_ in range(int(3.2 / .0625)):
        t = tc + r_ * .0625 + (j * .011)
        v = .55 * (1 - r_ / 55) ** 1.3 + .05 * rng.random()
        if v > .08: put('marA', 'marimba', p, t, .3, float(np.clip(v, .08, 1)), -.3 + .12 * j, .45)
for j, p in enumerate(['D3', 'A3', 'F#4', 'E5']):
    put('brass', 'horn', p, tc, 3.4, .45, -.2 + .15 * j, .38, release=1.5, attack=.25)
put('bass', 'contrabass_pizz', 'D2', tc, 3.0, .8, 0, .8)
put('pad', 'vibraphone_bowed', FIRST, tc + .2, 3.2, .38, .1, .5, release=1.5, attack=.4)

# ============ Mix ============
GAIN = {'marA': 1.0, 'marB': .85, 'bass': .95, 'glock': .8, 'perc': .7, 'brass': .8, 'pad': .9}
mix = np.zeros((N, 2), np.float32)
for k, x in stems.items():
    mix += x * GAIN[k]
wet = S.room(mix, size=.42, mix=.16)
mix = wet[:int(DUR * SR)]
# Fade out at the end to 38s
a, b = int(35.5 * SR), int(DUR * SR); mix[a:b] *= np.linspace(1, 0, b - a)[:, None] ** 1.5
# 24.0–24.7 true silence (clear the reverb tail, before the first duck)
a, b = int(24.05 * SR), int(24.7 * SR); mix[a:b] *= 0.0
pk = np.abs(mix).max(); mix *= .89 / pk   # ≈ -1 dBFS
for c in range(2): mix[:, c] = limit(mix[:, c], .9)
sf.write(os.path.join(HERE, 'score.wav'), mix, SR)
os.makedirs(os.path.join(HERE, 'stems'), exist_ok=True)
for k, x in stems.items(): sf.write(os.path.join(HERE, 'stems', k + '.wav'), (x[:int(DUR * SR)] * GAIN[k] * .89 / pk).astype(np.float32), SR)

cues = dict(firstNote=3.0, secondNote=4.5, title=ev('letter'), carriages=ev('carriage'), hornChords=ev('hornChord'),
            tapeStop=[22.5, 24.0], silence=[24.0, 24.7], hops=ev('hop'), hopFail=tf, release=30.0, finalChord=34.0, fadeOut=[35.5, 38.0],
            firstNotePitch=FIRST, gated_steps=len(gate_log), gated_by_car=sum(1 for g in gate_log if g[1] == 'car'))
json.dump(cues, open(os.path.join(HERE, 'cues.json'), 'w'), indent=1)
open(os.path.join(HERE, 'CREDITS.txt'), 'w').write('\n'.join(S.credits(sorted(used))) + '\n')

# —— Self-check ——
mono = mix.mean(1)
def rms(a, b): x = mono[int(a * SR):int(b * SR)]; return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)
print('instruments:', sorted(used))
for name_, a, b in [('dawn', 0, 5), ('title', 5, 9), ('ix', 9, 14), ('train', 14, 19), ('jam', 19, 22.5), ('tape', 22.5, 24), ('rest', 24, 30), ('top', 30, 34), ('final', 34, 38)]:
    print(f'{name_:6s} {a:5.1f}-{b:5.1f}  RMS {rms(a, b):6.1f} dBFS')
X = np.abs(np.fft.rfft(mono)) ** 2; f = np.fft.rfftfreq(len(mono), 1 / SR); tot = X.sum()
for lo, hi in [(20, 120), (120, 500), (500, 2000), (2000, 8000), (8000, 20000)]:
    print(f'band {lo:5d}-{hi:5d} Hz: {10 * np.log10(X[(f >= lo) & (f < hi)].sum() / tot):6.1f} dB')
def onset(t):
    a = mono[int((t - .05) * SR):int(t * SR)]; b = mono[int(t * SR):int((t + .06) * SR)]
    return 20 * np.log10((np.abs(b).max() + 1e-9) / (np.abs(a).max() + 1e-9))
for t in [3.0, 4.5, 5.0, 14.5, 17.0, 20.0, 22.0, 24.8, 25.6, 26.4, 27.1, 27.8, 29.4, 30.0, 34.0]:
    print(f'onset @{t:5.2f}: +{onset(t):5.1f} dB')
print('gated steps', cues['gated_steps'], 'by car', cues['gated_by_car'])

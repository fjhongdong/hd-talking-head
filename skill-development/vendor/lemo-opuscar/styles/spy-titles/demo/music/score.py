"""Original score for "The Velvet Cipher": 1960s spy big band (E minor, 132 BPM)
Run: .venv/bin/python styles/spy-titles/demo/music/score.py
Output: music/score.wav, music/stems/*.wav, music/score.json, music/CREDITS_music.txt
Motif "B–A#–A–G | E" (three chromatic steps down from the fifth, then landing on the tonic; dotted: long–short–short–long–land); ends on Em6/9.
Brass stabs = cut points (trumpet_stac + trombone_stac doubled at the octave + crash); surf guitar on the low strings + home-made spring reverb.
"""
import sys, os, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
sys.path.insert(0, ROOT)
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, fftconvolve
from core.audio import sampler as S
from core.audio.sfx import SR, add, limit

HERE = os.path.dirname(os.path.abspath(__file__))
S.seed(7); RNG = np.random.default_rng(7)
BPM = 132; BEAT = 60 / BPM; BAR = 4 * BEAT; OFF = BEAT
def B(n, k=1.0): return OFF + (n - 1) * BAR + (k - 1) * BEAT
DUR = 45.5; N = int(DUR * SR)
bus = {k: np.zeros((N, 2), np.float32) for k in ['brass', 'guitar', 'bass', 'drums', 'perc']}
KEY = {}   # key times

def put(b, x, t, g=1.0, pan=0.0): add(bus[b], x, t, g, pan)
def swing(n, k8):          # eighth note k8 (0..7) of bar n, swing 0.6
    beat, half = divmod(k8, 2)
    return B(n, 1 + beat + (0.6 if half else 0))
def m(p): return S.midi(p)

# ─────────── brass ───────────
CH = {
    'Em7':   (['E2', 'E3', 'G3', 'B3', 'D4'], ['B4', 'D5', 'E5', 'G5']),
    'C7s11': (['C3', 'E3', 'A#3', 'F#3'], ['E4', 'A#4', 'C5', 'F#5']),
    'B7s9':  (['B2', 'D#3', 'A3', 'B3'], ['D#4', 'A4', 'D5', 'F#5']),
    'Em6':   (['E2', 'E3', 'B3', 'C#4'], ['G4', 'B4', 'C#5', 'E5']),
    'Fm6':   (['F2', 'F3', 'C4', 'D4'], ['G#4', 'C5', 'D5', 'F5']),
    'Em69':  (['E2', 'E3', 'B3', 'C#4', 'F#3'], ['G4', 'B4', 'C#5', 'F#5', 'E5']),
}
PRE = .008   # brass attacks take ~8ms to reach their peak: trigger early so the "hit" lands on the beat
def stab(t, ch, vel=.9, crash=True, name=None, dur=.18):
    """one punch: staccato trumpet + staccato trombone (bass doubled at the octave), cut off after ~0.25s"""
    tb, tp = CH[ch]
    for i, p in enumerate(tb):
        put('brass', S.note('trombone_stac', p, dur, vel, release=.08), t - PRE, .55, -.35 + i * .08)
    for i, p in enumerate(tp):
        put('brass', S.note('trumpet_stac', p, dur, vel, release=.08), t - PRE, .5, .1 + i * .1)
    # layer the attack of a sustained trombone note for a punchy "doo-wah" feel, but cut it off immediately
    put('brass', S.note('trombone', tb[1], .12, vel * .9, release=.06), t - PRE, .35, -.2)
    if crash: put('drums', S.hit('drum_kit', 'crash_left', vel), t, .55, .25)
    put('drums', S.hit('drum_kit', 'kick_drum_left', vel), t, .6, 0)
    if name: KEY.setdefault('hits', []).append({'name': name, 't': round(t, 4), 'chord': ch})

def long_chord(t, ch, dur, vel=.75, rel=.9, g=.45):
    tb, tp = CH[ch]
    for i, p in enumerate(tb): put('brass', S.note('trombone', p, dur, vel, release=rel), t, g * .9, -.35 + i * .08)
    for i, p in enumerate(tp): put('brass', S.note('trumpet', p, dur, vel, release=rel), t, g * .8, .1 + i * .1)

# motif: (pitch, length in beats). long–short–short–long–land
MOTIF = [('B', 1.5), ('A#', .5), ('A', .5), ('G', 1.5)]
def motif(inst, t, octv, vel=.75, g=.5, pan=0, land=True, land_dur=1.5, stac=False, bus_='brass'):
    x = t
    for nm, bt in MOTIF:
        d = bt * BEAT * (.55 if stac else .92)
        put(bus_, S.note(inst, f'{nm}{octv}', d, vel, release=.12), x, g, pan); x += bt * BEAT
    if land:
        put(bus_, S.note(inst, f'E{octv}', land_dur * BEAT, vel * 1.05, release=.3), x, g * 1.05, pan)

# ─────────── surf guitar + spring reverb ───────────
def spring_ir(dur=2.2):
    n = int(dur * SR); ir = np.zeros(n, np.float32)
    # dispersive chirp: one "boing" (highs arrive first, lows trail), repeated and decaying at the spring's round-trip period
    L = int(.032 * SR); tt = np.arange(L) / SR
    f = 3800 * np.exp(-tt / .012) + 180
    ch = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / .018)
    per = int(.041 * SR); g = .72
    k = 0; pos = int(.012 * SR)
    while pos + L < n and k < 60:
        seg = ch * (g ** k)
        if k: seg = np.convolve(seg, np.ones(1 + k // 3) / (1 + k // 3), 'same')   # each later repeat is blurrier
        ir[pos:pos + L] += seg * (1 if k % 2 == 0 else -.8); pos += per + (k % 3) * 37; k += 1
    tail = RNG.standard_normal(n) * np.exp(-np.arange(n) / SR / .55) * .08
    ir += tail.astype(np.float32)
    ir = sosfilt(butter(2, [160, 4200], 'band', fs=SR, output='sos'), ir).astype(np.float32)
    return ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)
def trem(x, hz=6.5, depth=.55, start=0.0):
    t = np.arange(len(x)) / SR; e = 1 - depth * (.5 + .5 * np.sin(2 * np.pi * hz * np.maximum(0, t - start)))
    e[t < start] = 1; return (x * e).astype(np.float32)
def gtr(t, p, dur=.6, vel=.85, g=.6, pan=-.15, tremolo=False, slide=None):
    x = S.note('electric_guitar', p, dur, vel, release=.25)
    if slide is not None:   # slide down: resample the tail to lower its pitch (twang slide)
        n0 = int(.06 * SR); tail = x[n0:]; semis = slide
        r = np.linspace(1, 2 ** (semis / 12), len(tail)); idx = np.cumsum(r); idx = idx[idx < len(tail) - 1]
        tail = np.interp(idx, np.arange(len(tail)), tail).astype(np.float32); x = np.concatenate([x[:n0], tail])
    if tremolo: x = trem(x, 7, .6, .15)
    put('guitar', x, t, g, pan)

# ─────────── walking bass ───────────
PROG = {2: 'E', 3: 'E', 4: 'C7', 5: 'B7', 6: 'E', 7: 'E', 8: 'A', 9: 'B7', 10: 'E', 11: 'C7', 12: 'B7',
        13: 'E', 14: 'E', 15: 'E', 16: 'C7', 17: 'B7', 18: 'B7', 20: 'E', 21: 'E'}
ROOT = {'E': 40, 'A': 45, 'C7': 36, 'B7': 35}
THIRD = {'E': 3, 'A': 3, 'C7': 4, 'B7': 4}
def walk_bar(n, vel=.8, g=.9, beats=4, nxt=None):
    c = PROG[n]; r = ROOT[c]; nr = ROOT.get(PROG.get(n + 1, 'E'), 40) if nxt is None else nxt
    line = [r, r + THIRD[c], r + 7, nr + (1 if RNG.random() < .5 else -1)]
    if n % 2 == 1 and c == 'E': line = [r, r + 7, r + 10, nr - 1]
    for k in range(beats):
        put('bass', S.note('jazz_bass', line[k], BEAT * .9, vel * (1.05 if k == 0 else .92), release=.1), B(n, 1 + k), g, 0)

# ─────────── drums: brushes / sticks ───────────
def brush_bar(n, vel=.35):
    for k8 in range(8):   # maracas as the brush swish
        put('perc', S.hit('world_perc', 'egg_shaker_soft', .35 + .15 * (k8 % 2 == 0)), swing(n, k8), .32, .3)
    for bt in (2, 4):
        put('drums', S.hit('drum_kit', 'snare_rest_1', vel), B(n, bt), .5, -.1)
        put('drums', S.hit('drum_kit', 'hi_hat_closed', .35), B(n, bt), .35, .35)
def stick_bar(n, vel=.6, ride=True):
    for k8 in range(8):
        put('drums', S.hit('drum_kit', 'ride_left' if ride else 'hi_hat_closed', .45 + .15 * (k8 % 2 == 0)), swing(n, k8), .35, .35)
    for bt in (2, 4): put('drums', S.hit('drum_kit', 'snare_1', vel), B(n, bt), .5, -.1)
    for bt in (1, 3): put('drums', S.hit('drum_kit', 'kick_drum_left', .5), B(n, bt), .45)
def rail_bar(n, vel=.5, acc=()):
    """rail rhythm: snare sixteenths, 1st and 3rd sixteenths accented (clickety-clack)"""
    for k in range(16):
        t = B(n) + k * BEAT / 4
        v = vel * (1.0 if k % 4 == 0 else .72 if k % 4 == 2 else .45)
        put('drums', S.hit('drum_kit', 'snare_2', v), t, .42, -.05)
    for bt in (1, 3): put('drums', S.hit('drum_kit', 'kick_drum_left', .6), B(n, bt), .5)
    for k8 in range(8): put('drums', S.hit('drum_kit', 'hi_hat_closed', .45), B(n) + k8 * BEAT / 2, .28, .35)
    for t in acc: put('drums', S.hit('drum_kit', 'snare_1', .9), t, .7, -.05)
def bongo(t, which='bongo_high', v=.7, g=.55, pan=.3): put('perc', S.hit('world_perc', which, v), t, g, pan)

# ════════════════ Score ════════════════
# cold open: two bongo pickups
bongo(B(1, 3.5), 'bongo_low_high_velocity', .75, .6, .2); bongo(B(1, 4), 'bongo_high', .8, .6, .35)
KEY['bongo_pickup'] = [round(B(1, 3.5), 4), round(B(1, 4), 4)]

# stab 1 + walking bass/brushes
stab(B(2), 'Em7', .95, name='split')
gtr(B(2), 'E2', 1.2, .9, .55, slide=-5)
for n in (2, 3, 4, 5, 6, 7, 8, 9): walk_bar(n, .78 if n < 6 else .82)
brush_bar(2, .3); brush_bar(3, .32); brush_bar(4, .3); brush_bar(5, .34)
for i, t in enumerate([B(2, 2), B(2, 3), B(2, 4)]):   # the three words land
    put('drums', S.hit('drum_kit', 'snare_1', .5 + .1 * i), t, .45, -.1)
# sneaky: guitar plays the motif softly on the low strings
motif('electric_guitar', B(3, 1.5), 2, vel=.55, g=.45, pan=-.2, land_dur=1.2, bus_='guitar')
# stab 2 (short "tsh") + twang slide down
stab(B(4), 'C7s11', .9, name='snatch', dur=.12)
gtr(B(4), 'B2', .9, .9, .6, slide=-7)
put('drums', S.hit('drum_kit', 'crash_right', .55), B(4, 3), .3, -.3)   # cymbal tail for the trench-coat wipe
# agent entrance: motif "dun—dun-dun" timed to his head turn
for t, p in [(B(5, 3), 'B2'), (B(5, 3.5), 'A#2'), (B(5, 4), 'A2')]: gtr(t, p, .35, .85, .6)
gtr(B(5, 4.5), 'G2', .4, .8, .55)
# airport: twang hard-cuts in; brushes → sticks; trombone pad + muted-trumpet motif
gtr(B(6), 'E2', 1.6, .95, .65, tremolo=True)
brush_bar(6, .36)
put('brass', S.note('trombone', 'G3', BAR * .95, .45, release=.4, attack=.25), B(6), .3, -.3)
put('brass', S.note('trombone', 'B3', BAR * .95, .45, release=.4, attack=.25), B(6), .28, -.2)
stab(B(7), 'Em7', .9, name='hide')
brush_bar(7, .3)
put('brass', S.note('trombone', 'E3', BAR * 1.9, .4, release=.5, attack=.4), B(7, 2), .28, -.3)
stick_bar(8, .45, ride=False)
motif('trumpet_mute', B(8, 1), 4, vel=.6, g=.42, pan=.25, land_dur=2)
stick_bar(9, .55)
put('brass', S.note('trombone', 'B2', BAR * .8, .55, release=.3, attack=.3), B(9), .35, -.3)
put('brass', S.note('trombone', 'D#3', BAR * .8, .55, release=.3, attack=.3), B(9), .32, -.2)
for k in range(6):   # drum fill 16.364–16.818
    put('drums', S.hit('drum_kit', ['tom_1', 'tom_2', 'tom_3', 'snare_1', 'tom_3', 'tom_4'][k], .6 + .05 * k), B(9, 4) + k * BEAT / 6 * 1.0, .5, -.2 + k * .08)
KEY['fill_airport'] = round(B(9, 4), 4)

# train
stab(B(10), 'Em7', .95, name='train')
for n in (10, 11): walk_bar(n, .85)
rail_bar(10, .45)
rail_bar(11, .5, acc=[B(11, 1), B(11, 3)])     # carriage-jump accents 18.636, 19.545
KEY['jumps'] = [round(B(11, 1), 4), round(B(11, 3), 4)]
motif('trumpet', B(10, 2), 4, vel=.62, g=.32, pan=.2, land=False, stac=True)   # narration from 17.45: soft
motif('trombone', B(10, 2), 2, vel=.6, g=.3, pan=-.3, land=False, stac=True)
put('brass', S.note('trumpet', 'E5', BEAT * 1.8, .7, release=.2), B(11, 1), .35, .2)
put('brass', S.note('trombone', 'E3', BEAT * 1.8, .7, release=.2), B(11, 1), .38, -.3)
for k, p in enumerate(['G4', 'A4', 'A#4', 'B4']):   # climb to stab 5
    put('brass', S.note('trumpet_stac', p, .14, .75, release=.06), B(11, 3) + k * BEAT / 2, .4, .25)
    put('brass', S.note('trombone_stac', S.midi(p) - 12, .14, .75, release=.06), B(11, 3) + k * BEAT / 2, .42, -.25)
walk_bar(12, .85, beats=1)
stab(B(12), 'B7s9', .98, name='freeze', dur=.1)
KEY['stop_time'] = [20.60, round(B(12, 3), 4)]
# back in after the stop-time
rail_bar(12, .5) if False else None
for k in range(8):   # second half of bar 12: full band back in (from beat 3)
    t = B(12, 3) + k * BEAT / 4
    put('drums', S.hit('drum_kit', 'snare_2', .55 if k % 2 == 0 else .35), t, .42)
stab(B(12, 3), 'Em7', .85, crash=True, name='resume', dur=.14)
put('bass', S.note('jazz_bass', 'E2', BEAT * .9, .9, release=.1), B(12, 3), .9)
put('bass', S.note('jazz_bass', 'D#2', BEAT * .9, .85, release=.1), B(12, 4), .9)
for k in range(4): bongo(B(12, 4) + k * BEAT / 4, 'bongo_high' if k % 2 else 'bongo_low_high_velocity', .6 + .08 * k, .5)   # wheel close-up roll

# casino: bongos + maracas for a Latin feel, guitar tremolo
stab(B(13), 'Em6', .95, name='roulette')
walk_bar(13, .85); walk_bar(14, .85, beats=2)
LAT = [(0, 'bongo_high'), (.75, 'bongo_muted'), (1.5, 'bongo_low_high_velocity'), (2, 'bongo_high'), (2.75, 'bongo_muted'), (3.5, 'bongo_low_low_velocity')]
for n in (13, 14):
    for bt, w in LAT:
        if n == 14 and bt >= 2: break
        bongo(B(n, 1 + bt), w, .7, .5, .35)
    for k in range(8): put('perc', S.hit('world_perc', 'maracas_fw' if k % 2 == 0 else 'maracas_bw', .5), B(n) + k * BEAT / 2, .35, -.35)
gtr(B(13, 1.5), 'E3', 1.4, .8, .45, tremolo=True, pan=-.3)
gtr(B(13, 3), 'B2', .8, .85, .55, slide=-12)   # placing the bet: slide
KEY['keyBet'] = round(B(13, 3), 4)
stick_bar(13, .45, ride=False)
# pupil (a semitone higher)
stab(B(14, 3), 'Fm6', .98, name='pupil', dur=.14)
put('bass', S.note('jazz_bass', 'F2', BEAT * 1.8, .9, release=.12), B(14, 3), .9)
put('drums', S.hit('drum_kit', 'tom_1', .8), B(14, 4), .45, -.2); put('drums', S.hit('drum_kit', 'tom_3', .8), B(14, 4.5), .45, .1)

# rooftops: shout chorus
stab(B(15), 'Em7', 1.0, name='moon')
for n in (15, 16): walk_bar(n, .9); stick_bar(n, .7)
put('drums', S.hit('drum_kit', 'crash_left', .7), B(16), .45, .25)
# trumpet shouts the motif high (narration 26.15–28.3: a bit softer in the first half, push again at the end of the line)
motif('trumpet', B(15, 1.5), 5, vel=.68, g=.3, pan=.2, land=False)
motif('trombone', B(15, 1.5), 3, vel=.62, g=.26, pan=-.25, land=False)
for bt in (1.5, 2.5, 3.5, 4.5):   # trombone off-beat "boom"
    for p in ('E3', 'B3'): put('brass', S.note('trombone_stac', p, .12, .7, release=.06), B(16, bt), .3, -.3)
put('brass', S.note('trumpet', 'E5', BEAT * 1.4, .85, release=.15), B(16, 1), .38, .2)
put('brass', S.note('trumpet', 'G5', BEAT * .9, .85, release=.1), B(16, 2.5), .36, .2)
# sudden stop 28.636 = brass staccato; 29.09 courier turns back
stab(B(16, 3), 'C7s11', .9, crash=False, name='edge', dur=.1)
stab(B(16, 4), 'B7s9', .8, crash=False, name='cornered', dur=.1)

# build-up: chromatic climb B→C→C#→D, one per beat + toms
for k, p in enumerate(['B', 'C', 'C#', 'D']):
    t = B(17, 1 + k); v = .55 + .1 * k
    put('brass', S.note('trumpet', f'{p}5', BEAT * .98, v, release=.08, attack=.03), t, .3 + .04 * k, .2)
    put('brass', S.note('trumpet', f'{p}4', BEAT * .98, v, release=.08, attack=.03), t, .26 + .04 * k, .05)
    put('brass', S.note('trombone', f'{p}3', BEAT * .98, v, release=.08, attack=.03), t, .3 + .04 * k, -.25)
    put('brass', S.note('trombone', f'{p}2', BEAT * .98, v, release=.08, attack=.03), t, .28 + .04 * k, -.35)
    put('drums', S.hit('drum_kit', ['tom_4', 'tom_3', 'tom_2', 'tom_1'][k], .7 + .07 * k), t, .55, -.2 + .1 * k)
    put('bass', S.note('jazz_bass', ROOT['B7'] + [0, 1, 2, 3][k], BEAT * .9, .85, release=.1), t, .9)
put('drums', S.hit('drum_kit', 'crash_right', .85), B(17, 3), .6, -.2)   # key caught
KEY['catch'] = round(B(17, 3), 4)

# fragments fly back: snare sixteenths crescendo + sustained B7 crescendo
for k in range(16):
    t = B(18) + k * BEAT / 4; v = .35 + .6 * k / 15
    put('drums', S.hit('drum_kit', 'snare_1', v), t, .35 + .35 * k / 15, -.05)
    if k % 4 == 0: put('drums', S.hit('drum_kit', 'kick_drum_left', .5 + .1 * k / 4), t, .5)
tb, tp = CH['B7s9']
for i, p in enumerate(tb): put('brass', S.note('trombone', p, BAR * .97, .8, release=.05, attack=BAR * .8), B(18), .42, -.35 + i * .08)
for i, p in enumerate(tp): put('brass', S.note('trumpet', p, BAR * .97, .8, release=.05, attack=BAR * .8), B(18), .36, .1 + i * .1)
put('bass', S.note('jazz_bass', 'B1', BAR * .95, .9, release=.1), B(18), .9)
put('drums', S.hit('drum_kit', 'crash_left', .5), B(18), .3, .3)

# title: one last full-band stab + crash, sustained Em6/9
stab(B(19), 'Em69', 1.0, name='title')
long_chord(B(19), 'Em69', 1.1, .85, rel=1.1, g=.4)
put('bass', S.note('jazz_bass', 'E1', 2.5, 1.0, release=.8), B(19), 1.0)
put('drums', S.hit('drum_kit', 'crash_right', .9), B(19), .5, -.3)
put('guitar', S.note('electric_guitar', 'E2', 2.4, .9, release=.8), B(19), .55, -.15)

# held breath: only walking bass + closed hi-hat
walk_bar(20, .7, g=.85)
for k8 in range(8): put('drums', S.hit('drum_kit', 'hi_hat_closed', .4), swing(20, k8), .3, .35)

# button "boom—DA!"
stab(B(21) - BEAT * .5, 'Em69', .8, crash=False, dur=.1)           # "boom" (before the off-beat)
KEY.setdefault('hits', []).append({'name': 'button_pickup', 't': round(B(21) - BEAT * .5, 4), 'chord': 'Em69'})
stab(B(21), 'Em69', 1.0, crash=False, name='button', dur=.1)       # "DA!"
put('drums', S.hit('drum_kit', 'snare_1', 1.0), B(21), .7)
put('bass', S.note('jazz_bass', 'E2', .15, 1.0, release=.05), B(21), 1.0)
KEY['silence_end'] = [37.10, round(B(21, 3), 4)]
# one bongo after the silence (dry)
bongo(B(21, 3), 'bongo_high', .85, .75, .15)
KEY['bongo_end'] = round(B(21, 3), 4)

# end: surf guitar low E + long spring tail, bass in unison; very soft muted-trumpet motif
gtr(B(23, 2), 'E2', 3.5, .95, .7, tremolo=True)
put('bass', S.note('jazz_bass', 'E1', 3.0, .85, release=1.2), B(23, 2), .85)
motif('trumpet_mute', B(23, 3.5), 4, vel=.4, g=.22, pan=.3, land_dur=3)
KEY['end_guitar'] = round(B(23, 2), 4)

# ════════════════ Mix ════════════════
ir = spring_ir()
g = bus['guitar']
wet = np.stack([fftconvolve(g[:, c], ir)[:N] for c in range(2)], 1).astype(np.float32)
bus['guitar'] = (g * .75 + wet * .55) * 1.8
bus['brass'] = S.room(bus['brass'], size=.35, mix=.16, damp=.55)
bus['drums'] = S.room(bus['drums'], size=.25, mix=.1, damp=.6)
bus['perc'] = S.room(bus['perc'], size=.2, mix=.08)
bus['bass'] = sosfilt(butter(2, 30, 'high', fs=SR, output='sos'), bus['bass'], axis=0).astype(np.float32)
# tame the highs: cymbals slightly cut above 8k
bus['drums'] = (bus['drums'] - .35 * sosfilt(butter(2, 9000, 'high', fs=SR, output='sos'), bus['drums'], axis=0)).astype(np.float32)

# silence gate: digital zero (reverb tails included)
gate = np.ones(N, np.float32)
def silence(a, b, fo=.03, fi=.002):
    ia, ib = int(a * SR), int(b * SR); f = int(fo * SR)
    if ia - f >= 0 and f > 0: gate[ia - f:ia] *= np.linspace(1, 0, f)
    gate[ia:ib] = 0
    k = int(fi * SR); gate[ib:ib + k] *= np.linspace(0, 1, k)
silence(0, B(1, 3.5) - .01, fo=.0001)          # cold open: all zero before the bongos
silence(20.60, B(12, 3))                      # stop-time
silence(37.10, B(21, 3))                      # one beat of silence at the end
silence(B(21, 3) + .9, 40.909 - .005, fo=.25) # narration window: nothing at all
for k in bus: bus[k] *= gate[:, None]
# fade-out at the end
fo = np.ones(N, np.float32); ia = int(44.3 * SR); fo[ia:] = np.linspace(1, 0, N - ia) ** 1.5
for k in bus: bus[k] *= fo[:, None]

mix = sum(bus.values())
pk = np.abs(mix).max(); tgt = 10 ** (-1.2 / 20)
sc = tgt / pk
for k in bus: bus[k] *= sc
mix = mix * sc
assert np.isfinite(mix).all()
os.makedirs(os.path.join(HERE, 'stems'), exist_ok=True)
sf.write(os.path.join(HERE, 'score.wav'), mix, SR, subtype='PCM_24')
for k in bus: sf.write(os.path.join(HERE, 'stems', k + '.wav'), bus[k], SR, subtype='PCM_24')

# ════════════════ Self-check ════════════════
mono = mix.mean(1); br = bus['brass'].mean(1)
def onset(x, t, win=.06):
    # envelope (1ms smoothing), starting from the noise floor before t-30ms: the first point that exceeds "noise floor ×4 and ≥ 25% of peak"
    a = int((t - .03) * SR); b = int((t + win) * SR); e = np.convolve(np.abs(x[a:b]), np.ones(48) / 48, 'same')
    pre = e[:int(.01 * SR)].max(); thr = max(pre * 4, .25 * e.max()); i = np.argmax(e > thr); return (a + i) / SR
report = {'hits': []}
for h in KEY['hits']:
    o = onset(br, h['t']); h['measured'] = round(o, 4); h['dev_ms'] = round((o - h['t']) * 1000, 1); report['hits'].append(h)
zones = {}
for nm, (a, b) in {'stop_time': (20.60, B(12, 3)), 'final_silence': (37.10, B(21, 3)), 'cold_open_pre_bongo': (0, B(1, 3.5) - .011)}.items():
    seg = mix[int(a * SR) + 1:int(b * SR) - 1]; zones[nm] = {'from': round(a, 4), 'to': round(b, 4), 'max_abs': float(np.abs(seg).max())}
spec = np.abs(np.fft.rfft(mono)) ** 2; fr = np.fft.rfftfreq(len(mono), 1 / SR)
band = lambda lo, hi: float(10 * np.log10(spec[(fr >= lo) & (fr < hi)].sum() / spec.sum() + 1e-12))
bands = {'<200': band(20, 200), '200-2k': band(200, 2000), '2k-8k': band(2000, 8000), '8k-20k': band(8000, 20000)}
secs = [('cold_open', 0, 2.27), ('grid+velvet', 2.27, 7.73), ('agent_intro', 7.73, 9.55), ('airport', 9.55, 16.82), ('train', 16.82, 22.27),
        ('casino+pupil', 22.27, 25.91), ('rooftop', 25.91, 29.55), ('buildup+shatter', 29.55, 33.18), ('title', 33.18, 35.0), ('hold', 35.0, 36.82),
        ('vo_window', 38.7, 40.9), ('end_card', 40.9, 44.09)]
rms = {n: round(float(20 * np.log10(np.sqrt(np.mean(mono[int(a * SR):int(b * SR)] ** 2)) + 1e-9)), 1) for n, a, b in secs}
KEY.update({'bpm': BPM, 'off': OFF, 'dur_wav': DUR, 'zones': zones, 'bands_db_rel': bands, 'rms_dbfs': rms, 'peak_dbfs': round(float(20 * np.log10(np.abs(mix).max())), 2)})
json.dump(KEY, open(os.path.join(HERE, 'score.json'), 'w'), indent=1)
open(os.path.join(HERE, 'CREDITS_music.txt'), 'w').write('\n'.join(S.credits(['trumpet', 'trumpet_stac', 'trumpet_mute', 'trombone', 'trombone_stac', 'electric_guitar', 'jazz_bass', 'world_perc', 'drum_kit'])) + '\n')
print(json.dumps({'hits': [(h['name'], h['t'], h['dev_ms']) for h in report['hits']], 'zones': zones, 'bands': bands, 'rms': rms, 'peak': KEY['peak_dbfs']}, indent=1))

"""Solo cello: one melodic line that never breaks, with notes landing on the pen's corners (corners / segment markers in events.json).
cellos at low velocity, legato, to imitate a solo; childhood uses cellos_pizz; the ending uses hand_chimes. No piano, no string pad.
python styles/one-line/demo/music/score.py → music/score.wav + music/cues.json"""
import sys, os, json, numpy as np, soundfile as sf
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
sys.path.insert(0, ROOT)
from core.audio import sampler as S
from core.audio.sfx import SR, add
HERE = os.path.dirname(os.path.abspath(__file__))
E = json.load(open(os.path.join(HERE, '..', 'events.json')))
DUR = E['dur'] + 1.0
S.seed(7)

buf = np.zeros((int(DUR * SR), 2), np.float32)
PAN = -0.12   # one instrument, sitting beside the artist slightly to the left

def legato(notes, vel=.5, attack=.12, tail=.9, gain=1.0, overlap=.14, first_attack=None):
    """notes = [(t, pitch[, vel])]; each note lasts until the next note's onset + overlap (legato bow change)"""
    for i, n in enumerate(notes):
        t, p = n[0], n[1]; v = n[2] if len(n) > 2 else vel
        t1 = notes[i + 1][0] + overlap if i + 1 < len(notes) else t + tail
        a = first_attack if (i == 0 and first_attack) else attack
        for pp in (p if isinstance(p, (list, tuple)) else [p]):
            x = S.note('cellos', pp, max(.2, t1 - t), vel=v, attack=a, release=.45)
            add(buf, x, t, gain, PAN)

def pizz(notes, vel=.62, gain=1.0):
    for n in notes:
        x = S.note('cellos_pizz', n[1], .9, vel=n[2] if len(n) > 2 else vel)
        add(buf, x, n[0], gain, PAN + .05)

cues = {}
# A grip: D–F#–A, the grip lands on D4 (first knuckle → last knuckle)
A = [(1.02, 'D3', .38), (2.43, 'F#3', .46), (3.31, 'A3', .5), (4.09, 'D4', .6)]
legato(A, first_attack=.9, tail=1.2, gain=1.25); cues['grip'] = 4.09
# B kite: pizzicato. The line climbs (rising eighth notes) → hair → the kite's four corners → two bows → reeling in (descending) → other half of the crown
B = [(4.95, 'D3'), (5.19, 'F#3'), (5.43, 'A3'), (5.67, 'D4'), (5.905, 'E4'),
     (6.40, 'F#4'), (6.60, 'A4'), (6.757, 'B4'), (6.904, 'D5', .7), (7.185, 'A4'),
     (7.352, 'F#4'), (7.598, 'G4'), (7.759, 'F#4'), (7.902, 'E4'),
     (8.047, 'D4', .55), (8.168, 'C#4', .52), (8.383, 'B3', .5), (8.563, 'A3', .48), (8.904, 'F#3', .5), (9.2, 'E3', .5)]
pizz(B, gain=.42)
# C cycling: arco returns, one rising phrase for each wheel
C = [(9.62, 'D3', .42), (10.35, 'A3', .48), (10.9, 'D4', .52), (11.455, 'F#4', .56), (11.784, 'E4', .5),
     (12.478, 'D4', .5), (12.687, 'C#4', .5), (13.2, 'A3', .48), (13.792, 'B3', .5)]
legato(C, first_attack=.35)
# D first love: the highest, most singing phrase of the piece; first nose-tip touch = top note B4, second = A4
D = [(14.04, 'D4', .5), (14.706, 'E4', .52), (15.292, 'F#4', .56), (15.469, 'G4', .58), (15.891, 'A4', .62), (16.11, 'B4', .66),
     (16.9, 'A4', .58), (17.391, 'G4', .55), (17.765, 'F#4', .55), (18.241, 'G4', .57), (18.417, 'A4', .62), (18.935, 'F#4', .52), (19.392, 'D4', .5)]
legato(D, overlap=.18); cues['nose1'] = 16.11; cues['nose2'] = 18.417
# E home: double stops, steady
Ech = [(19.868, ['G3', 'D4'], .44), (20.853, ['A3', 'E4'], .44), (21.337, ['F#3', 'D4'], .44), (21.816, ['E3', 'C#4'], .42), (22.075, ['D3', 'A3'], .42)]
legato(Ech, gain=1.0, attack=.2)
# F loss: B3 → A3, after the pen stops A3 fades to nothing; then true silence; at "goes on" a very soft F#3 as the bow sets down again
legato([(22.927, 'B3', .44), (23.483, 'A3', .42)], tail=1.0, gain=1.5)
cues['silence'] = [24.6, 26.85]
legato([(26.85, 'F#3', .32)], first_attack=.5, tail=.5, gain=1.5)
# G child: the "grip" motif returns unchanged, an octave higher
G = [(27.056, 'D4', .4), (28.085, 'F#4', .46), (29.408, 'A4', .5), (30.093, 'D5', .56)]
legato(G, first_attack=.4, tail=1.0, gain=1.5)
# H old age: slow descent in the low register; the register slowly rises during the zoom-out; the last few eyelashes get one note each, landing on the tonic D
H = [(30.8, 'D3', .42), (32.4, 'C#3', .42), (33.5, 'B2', .45), (34.6, 'D3', .48), (35.6, 'F#3', .5), (36.6, 'A3', .54),
     (37.298, 'B3', .5), (37.854, 'A3', .46), (38.403, 'F#3', .44)]
legato(H, attack=.3, overlap=.2, gain=1.7)
legato([(38.8, ['D2', 'D3'], .48)], attack=.25, tail=2.6, gain=1.3); cues['final'] = 38.8
# I hand-over: one handbell as the new line starts (a new voice), a very soft long high note at the end
add(buf, S.note('hand_chimes', 'D6', 4.0, vel=.55), 41.7, .9, .25); cues['chime'] = 41.7
add(buf, S.note('hand_chimes', 'A5', 3.5, vel=.35), 43.4, .6, .3)
legato([(44.3, 'A4', .26)], first_attack=1.2, tail=2.8, gain=1.6)

mix = S.room(buf, size=.55, mix=.22)
# silence zones are zeroed including the reverb tails (20 ms fade)
a, b = cues['silence']; i0, i1 = int(a * SR), int(b * SR); f = int(.3 * SR)
g = np.ones(len(mix), np.float32); g[i0:i1] = 0; g[i0 - f:i0] = np.linspace(1, 0, f); g[i1:i1 + int(.02 * SR)] = np.linspace(0, 1, int(.02 * SR))
mix *= g[:, None]
mix = mix / (np.abs(mix).max() + 1e-9) * .8
sf.write(os.path.join(HERE, 'score.wav'), mix, SR)
json.dump(cues, open(os.path.join(HERE, 'cues.json'), 'w'), indent=1)
print('score.wav', len(mix) / SR, 's', cues)
print('\n'.join(S.credits(['cellos', 'cellos_pizz', 'hand_chimes'])))

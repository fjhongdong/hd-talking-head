"""Original in-scene elevator music "Hold Music No. 9": 88 BPM, F major, 8-bar loop ×3
Vibraphone (soft mallets) melody + clean electric guitar lightly strumming chords on beats 2 and 4 + fingerstyle electric bass (root/fifth). All CC0 samples (VCSL / FreePats).
Writes music/muzak_raw.wav (original speed, dry); tape-speed change, through-the-wall filtering and reverb are done in mix.py."""
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
sys.path.insert(0, ROOT)
import numpy as np, soundfile as sf
from core.audio import sampler as S
S.seed(9)
BPM = 88; B = 60 / BPM; BAR = 4 * B
CH = [('Fmaj7', ['F2', 'C3'], ['A3', 'C4', 'E4', 'F4']), ('Dm7', ['D2', 'A2'], ['F3', 'A3', 'C4', 'D4']),
      ('Gm7', ['G2', 'D2'], ['F3', 'Bb3', 'D4', 'G4']), ('C7', ['C2', 'G2'], ['E3', 'Bb3', 'C4', 'E4']),
      ('Am7', ['A2', 'E2'], ['G3', 'C4', 'E4', 'A4']), ('D7', ['D2', 'A2'], ['F#3', 'C4', 'D4', 'A4']),
      ('Gm7', ['G2', 'D2'], ['F3', 'Bb3', 'D4', 'G4']), ('C7sus', ['C2', 'G2'], ['F3', 'Bb3', 'C4', 'G4'])]
# Melody (per bar: [(note, beats)], None = rest)
MEL = [[('A4', 2), ('C5', 1), ('E5', 1)], [('D5', 3), ('C5', 1)], [('Bb4', 2), ('D5', 1), ('F5', 1)], [('E5', 3), (None, 1)],
       [('E5', 2), ('C5', 1), ('A4', 1)], [('F#4', 2), ('A4', 1), ('C5', 1)], [('Bb4', 1), ('A4', 1), ('G4', 2)], [('G4', 2), ('E4', 2)]]
MEL2 = [[('C5', 2), ('A4', 1), ('C5', 1)], [('F5', 2), ('E5', 1), ('D5', 1)], [('D5', 3), ('Bb4', 1)], [('C5', 2), ('G4', 2)],
        [('A4', 1), ('C5', 1), ('E5', 2)], [('D5', 2), ('C5', 1), ('A4', 1)], [('G4', 2), ('Bb4', 1), ('A4', 1)], [('F4', 4)]]
ev = []; LOOPS = 3
for L in range(LOOPS):
    for b, (name, bass, voic) in enumerate(CH):
        t0 = (L * 8 + b) * BAR
        ev.append((t0, 'electric_bass', bass[0], B * 1.8, .55, 0))
        ev.append((t0 + 2 * B, 'electric_bass', bass[1], B * 1.6, .45, 0))
        for beat in (1, 3):
            for k, p in enumerate(voic):
                ev.append((t0 + beat * B + k * .012, 'electric_guitar', p, B * .55, .32, .35))
        t = t0
        for p, d in (MEL if L % 2 == 0 else MEL2)[b]:
            if p: ev.append((t, 'vibraphone', p, d * B * .95, .55, -.25))
            t += d * B
mix = S.render(ev, dur=LOOPS * 8 * BAR + 2)
mix = S.room(mix, size=.35, mix=.15)
mix /= np.abs(mix).max() + 1e-9
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'muzak_raw.wav')
sf.write(out, (mix * .9).astype(np.float32), 48000); print(out, len(mix) / 48000)

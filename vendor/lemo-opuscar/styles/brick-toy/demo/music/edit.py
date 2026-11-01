# Score edit → score.wav (48k stereo, full film length)
# Section A: Monkeys Spinning Monkeys, first beat aligned to the first brick (4.0s), hard cut at the moment of collapse
# Rebuild: a quiet passage of the same track returns (-9dB), downbeat aligned to "finds the nose cone"
# Lift-off: Heroic Age's burst at 53.61s aligned to ignition, jump 60.53→79.02 skipping 10 bars (similarity .95), final accent lands on the end card
import numpy as np, soundfile as sf, librosa, warnings, json; warnings.filterwarnings('ignore')
SR, DUR = 48000, 54.0
out = np.zeros((int(SR * DUR), 2))
def load(f):
    y, _ = librosa.load(f, sr=SR, mono=False); return y.T if y.ndim > 1 else np.stack([y, y], 1)
def place(y, song0, song1, at, gain=1.0, fin=.01, fout=.03):
    a, b = int(song0 * SR), int(song1 * SR); seg = y[a:b].copy() * gain
    n = len(seg); ramp = lambda k: np.linspace(0, 1, max(1, int(k * SR)))[:, None]
    fi = ramp(fin); seg[:len(fi)] *= fi[:n]; fo = ramp(fout)[::-1]; seg[-len(fo):] *= fo[-n:]
    s = int(at * SR); e = min(len(out), s + n); out[s:e] += seg[:e - s]
M = load('Monkeys_Spinning_Monkeys.mp3'); mb = np.load('Monkeys_Spinning_Monkeys_beats.npy')
FALL = 4.0 + 32 * 60 / 143.555
place(M, 0.0, FALL - 3.93, 3.93, 1.6, .01, .025)   # original is quiet; +4dB to bring it closer to the lift-off section
# rebuild section: take the downbeat (every 4 beats) near 64–70s and align it to 29.0
downs = mb[::4]; d = downs[np.abs(downs - 66.0).argmin()]; off = 29.0 - d
place(M, 26.4 - off, 32.62 - off, 26.4, 10 ** (-9 / 20), 1.0, .35)
Hh = load('Heroic_Age.mp3'); HOFF = 53.61 - 36.5
A, B = 60.53, 79.02; XF = .06
place(Hh, 53.0, A + XF / 2, 53.0 - HOFF, 1.0, .5, XF)
place(Hh, B - XF / 2, 90.5, A - HOFF - XF / 2, 1.0, XF, 1.2)
pk = np.abs(out).max(); out *= .89 / pk
sf.write('score.wav', out, SR)
json.dump({'final_hit': 87.307 - HOFF - (B - A), 'reprise_downbeat_song': float(d)}, open('score.json', 'w'))
print('peak norm', pk, 'final hit video', 87.307 - HOFF - (B - A))

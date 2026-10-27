"""Bicycle bell (a lever striking a small metal bell): bell(n_rings=2, sr=48000, seed=0, v=1.0) → mono float32

One "ring" = the lever strikes ~5 times in a row (~18 Hz), giving a "ring-a-ling"; n_rings rings spaced 0.34 s apart.
Bell partials: two inharmonic main partials at 2100 Hz / 3400 Hz (each with a twin partial a few Hz away → metallic shimmer),
plus a weak 5230 Hz partial; each strike has a short metallic transient (high-passed noise, 1.5 ms).
"""
import numpy as np
from scipy.signal import butter, sosfilt

PARTIALS = [  # (Hz, amplitude, decay tau s)
    (2100, 1.00, .55), (2106.5, .55, .60),
    (3400, .62, .32), (3409, .30, .28),
    (5230, .16, .12), (1045, .10, .25),
]


def strike(sr=48000, dur=1.2, v=1.0, rng=None):
    rng = rng or np.random.default_rng(0)
    n = int(dur * sr); t = np.arange(n) / sr
    x = np.zeros(n)
    for f, a, tau in PARTIALS:
        x += a * np.sin(2 * np.pi * f * (1 + rng.normal(0, .0004)) * t + rng.random() * 6.28) * np.exp(-t / tau)
    tr = rng.standard_normal(int(.004 * sr)) * np.exp(-np.arange(int(.004 * sr)) / (sr * .0015))
    tr = sosfilt(butter(2, 3000, 'high', fs=sr, output='sos'), tr)
    x[:len(tr)] += tr * .9
    return x * v


def bell(n_rings=2, sr=48000, seed=0, v=1.0, single=False):
    rng = np.random.default_rng(seed)
    hits = []
    if single:
        hits = [(0.0, 1.0)]
    else:
        for r in range(n_rings):
            t0 = r * .34
            k = 5
            for i in range(k):
                hits.append((t0 + i / 18.0 + rng.normal(0, .003), (1.0 if i == 0 else .62 - .06 * i) * (1 - .1 * r)))
    dur = hits[-1][0] + 1.3
    out = np.zeros(int(dur * sr))
    for t0, a in hits:
        s = strike(sr, 1.2, a, rng)
        i = int(max(0, t0) * sr)
        # each strike partly damps the previous one (the lever presses on the bell)
        out[i:] *= .82
        out[i:i + len(s)] += s[:len(out) - i]
    out = sosfilt(butter(2, 700, 'high', fs=sr, output='sos'), out)
    out = sosfilt(butter(2, 9000, 'low', fs=sr, output='sos'), out)
    m = np.abs(out).max()
    return (out / m * .9 * v).astype(np.float32)


if __name__ == '__main__':
    import soundfile as sf, os
    sf.write(os.path.join(os.path.dirname(__file__), 'bell_test.wav'), np.concatenate([bell(2), np.zeros(4800), bell(single=True)]), 48000)

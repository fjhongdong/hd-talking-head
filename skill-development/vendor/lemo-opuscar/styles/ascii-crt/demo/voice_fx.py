"""AI voice treatment:voices_raw/*.wav → voices/*.wav
Light ring modulation (52Hz, 16% wet) + 6ms comb resonance (metallic cavity feel) + band-pass 140–7000Hz + slight saturation. If whisper becomes unreliable, lower RING/COMB."""
import json, os, sys, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
D = os.path.dirname(os.path.abspath(__file__))
RING, COMB = .16, .22
lines = json.load(open(os.path.join(D, 'lines.json')))
os.makedirs(os.path.join(D, 'voices'), exist_ok=True)
dur = {}
for L in lines:
    y, sr = sf.read(os.path.join(D, 'voices_raw', L['id'] + '.wav'))
    t = np.arange(len(y)) / sr
    y = y * (1 - RING) + y * np.sin(2 * np.pi * 52 * t) * RING * 1.6
    k = int(.006 * sr); z = y.copy()
    for _ in range(3): z[k:] = z[k:] + COMB * z[:-k] * .8; 
    y = y * (1 - COMB) + z * COMB
    y = sosfilt(butter(2, [140, 7000], 'bandpass', fs=sr, output='sos'), y)
    y = np.tanh(y / np.abs(y).max() * 1.4) * .8
    sf.write(os.path.join(D, 'voices', L['id'] + '.wav'), y.astype(np.float32), sr)
    dur[L['id']] = round(len(y) / sr, 3)
json.dump(dur, open(os.path.join(D, 'voices', 'dur.json'), 'w'), indent=1)
print(dur)

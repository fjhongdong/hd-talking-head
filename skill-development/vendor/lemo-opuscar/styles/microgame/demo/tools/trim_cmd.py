"""One-word commands: when Kokoro reads a single word it adds a vowel tail at the end (Pump → "Pompey").
Fix: generate "Pump, now!", keep only the first word using whisper word timestamps, 40ms fade-out at the end. python trim_cmd.py lines.json voices"""
import sys, json, os, numpy as np, soundfile as sf
from faster_whisper import WhisperModel
import librosa
m = WhisperModel('base.en', device='cpu', compute_type='int8')
L = json.load(open(sys.argv[1])); vd = sys.argv[2]; dur = json.load(open(os.path.join(vd, 'dur.json')))
for x in L:
    if 'trim' not in x: continue
    f = os.path.join(vd, x['id'] + '.wav'); y, sr = sf.read(f)
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000); pad = np.zeros(int(.6 * 16000))
    segs, _ = m.transcribe(np.concatenate([pad, y16, pad]).astype(np.float32), language='en', word_timestamps=True)
    ws = [w for s in segs for w in s.words]
    end = ws[0].end - .6 + .03
    # cut at the lowest-energy point after the word end (search at most 80ms further)
    n = int(end * sr); win = int(.08 * sr); seg = np.abs(y[n:n + win]); cut = n + (int(np.argmin(np.convolve(seg, np.ones(64) / 64, 'same'))) if len(seg) > 64 else 0)
    y = y[:cut].copy(); fo = int(.04 * sr); y[-fo:] *= np.linspace(1, 0, fo)
    sf.write(f, y, sr); dur[x['id']] = round(len(y) / sr, 3); x['asr'] = x['trim']
    print(x['id'], 'trimmed to', dur[x['id']], 's (first word:', ws[0].word, ')')
json.dump(dur, open(os.path.join(vd, 'dur.json'), 'w'), indent=1)
json.dump(L, open(sys.argv[1] + '.asr.json', 'w'), indent=1)

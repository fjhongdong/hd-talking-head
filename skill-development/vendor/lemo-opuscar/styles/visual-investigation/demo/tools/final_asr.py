#!/usr/bin/env python3
"""Speech check on the FINAL mix (music, foley, newsreel sound and all): every narration line is cut out of the
finished film (its own window, 0.3 s either side) and transcribed with faster-whisper, then compared with the
script by characters after normalising numbers and punctuation. Per-line windows avoid Whisper's timestamp drift
on long files.      $LIB/.venv/bin/python tools/final_asr.py <film.mp4> [--model base.en]"""
import json, os, re, subprocess, sys, tempfile, difflib
DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
film = sys.argv[1]; model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'base.en'
from faster_whisper import WhisperModel
M = WhisperModel(model, device='cpu', compute_type='int8')
NW = {'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10'}
norm = lambda t: ''.join(NW.get(w, w) for w in re.sub(r'[^a-z0-9 ]', ' ', re.sub(r'(\d),(\d)', r'\1\2', t.lower())).split())
lines = json.load(open(os.path.join(DEMO, 'audio', 'lines.json'))); at = json.load(open(os.path.join(DEMO, 'film.json')))['vo']
dur = json.load(open(os.path.join(DEMO, 'audio', 'vo', 'dur.json'))); bad = 0
for l in lines:
    k = l['id']; t0 = max(0, at[k] - .3); d = dur[k] + .6
    tmp = tempfile.mktemp(suffix='.wav', dir=os.path.join(DEMO, 'out'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t0:.2f}', '-t', f'{d:.2f}', '-i', film, '-ac', '1', '-ar', '16000', tmp], check=True)
    segs, _ = M.transcribe(tmp, language='en'); heard = ' '.join(s.text for s in segs); os.remove(tmp)
    want = l.get('asr') or l['text']; r = difflib.SequenceMatcher(None, norm(want), norm(heard)).ratio(); ok = r >= .85; bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {k} {r:.2f} | {want} → {heard.strip()}")
print('final mix speech check:', 'OK' if not bad else f'{bad} lines below 0.85')
sys.exit(1 if bad else 0)

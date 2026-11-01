#!/usr/bin/env python3
"""Speech check on the FINAL mix (music, foley and all): cut each narration line out of the finished film
(its start to its end, plus 0.4 s either side), transcribe that excerpt with faster-whisper and compare it with
the script by recall (share of the line's words heard; numbers normalised).
Per-line excerpts, because Whisper's 30-s long-form windows drop words at their boundaries on a whole-film pass.
    $LIB/.venv/bin/python tools/final_asr.py <film.mp4> [--model base.en]"""
import json, os, re, subprocess, sys, tempfile
DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
film = sys.argv[1]; model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'base.en'
from faster_whisper import WhisperModel
M = WhisperModel(model, device='cpu', compute_type='int8')
WORDS = [('four and a half', '4.5'), ('forty-four', '44'), ('forty four', '44'), ('nine', '9'), ('eighty', '80'), ('fifth', '5th'),
         ('four hundred and ten', '410'), ('twenty-five hundred', '2500'), ('four thousand', '4000'), ('twelve hundred and fifty', '1250')]
def norm(t):
    t = t.lower()
    for a, b in WORDS: t = t.replace(a, b)
    t = re.sub(r'(\d)\s*,\s*(\d)', r'\1\2', t).replace('1st', '1')
    t = re.sub(r'\bsteal\b', 'steel', t)      # homophone: on a 3-s excerpt Whisper may write "first steal" (the isolated line and the whole-film pass both transcribe it as steel)
    return [w.strip('.') for w in re.sub(r'[^a-z0-9. ]', ' ', t).split() if w.strip('.')]
lines = json.load(open(os.path.join(DEMO, 'audio', 'lines.json')))
ev = {e['id']: e['t'] for e in json.load(open(os.path.join(DEMO, 'events.json')))['ev'] if e['type'] == 'vo'}
dur = json.load(open(os.path.join(DEMO, 'audio', 'vo', 'dur.json')))
bad = 0
for l in lines:
    k = l['id']; a = max(0, ev[k] - .4); d = dur[k] + .8
    tmp = tempfile.mktemp(suffix='.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(a), '-t', str(d), '-i', film, '-ac', '1', '-ar', '16000', tmp], check=True)
    segs, _ = M.transcribe(tmp, language='en', condition_on_previous_text=False); os.remove(tmp)
    heard = ' '.join(s.text for s in segs)
    hw = norm(heard)
    r = max(sum(min(hw.count(x), ww.count(x)) for x in set(ww)) / max(1, len(ww)) for ww in (norm(l['text']), norm(l.get('asr') or l['text'])))
    ok = r >= .85; bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {k} {r:.2f} | {l['text']} → {heard.strip()}")
print('final mix speech check:', 'OK' if not bad else f'{bad} lines below 0.85')
sys.exit(1 if bad else 0)

"""Subtitle cues (for the .srt, command words included; same rules as film.js: hold ≥ max(1.8s, speech + 0.6s), command words ≥ 0.9s, never overlapping the next line) → out/srt.json"""
import json, os
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = [l for l in json.load(open(os.path.join(D, 'lines.json'))) if not l.get('fx')]
dur = json.load(open(os.path.join(D, 'voices/dur.json')))
out = []
for i, l in enumerate(L):
    t1 = l['t'] + max(.9 if l.get('cmd') else 1.8, dur[l['id']] + .6)
    if i + 1 < len(L): t1 = min(t1, L[i + 1]['t'] - .05)
    out.append({'t0': l['t'], 't1': round(t1, 3), 'text': (l.get('trim', l['text']).rstrip('.!') + '!').upper() if l.get('cmd') else l['text']})
os.makedirs(os.path.join(D, 'out'), exist_ok=True)
json.dump(out, open(os.path.join(D, 'out/srt.json'), 'w'), indent=1); print(len(out), 'cues')

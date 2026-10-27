"""Subtitle export: same rule as the subtitles burned in by the page (shown from 0.05s before the speech starts, for at least 1.8s and no shorter than the speech + 0.6s, never overlapping the next line)
Usage: .venv/bin/python styles/lowpoly-island/demo/subs.py → out/cues.json (then core/render/srt.py converts it to .srt)"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ev = [e for e in json.load(open(os.path.join(HERE, 'events.json')))['ev'] if e['type'] == 'vo']
dur = json.load(open(os.path.join(HERE, 'voices', 'dur.json')))
cues = []
for i, e in enumerate(ev):
    b = e['t'] + max(1.8, dur[e['id']] + .6)
    if i + 1 < len(ev): b = min(b, ev[i + 1]['t'] - .05)
    cues.append({'t0': round(e['t'] - .05, 3), 't1': round(b, 3), 'text': e['text']})
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
json.dump(cues, open(os.path.join(HERE, 'out', 'cues.json'), 'w'), indent=1)
for c in cues: print(c)

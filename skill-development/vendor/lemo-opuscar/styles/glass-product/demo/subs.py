"""Subtitle export: same rule as the subtitles burned in on the page (shown = max(1.9 s, speech + 0.7 s)); narration times taken from story.js
python styles/glass-product/demo/subs.py → demo/cues.json(then core/render/srt.py converts it to .srt)"""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'story.js')).read()
vo = re.findall(r"\{ id: '(v\d)', t: ([\d.]+), text: '([^']+)' \}", src)
dur = json.load(open(os.path.join(HERE, 'voices', 'dur.json')))
cues = [{'t0': float(t), 't1': round(float(t) + max(1.9, dur[i] + .7), 3), 'text': txt} for i, t, txt in vo]
json.dump(cues, open(os.path.join(HERE, 'cues.json'), 'w'), indent=1); print(cues)

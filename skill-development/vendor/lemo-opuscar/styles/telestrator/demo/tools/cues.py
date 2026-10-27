#!/usr/bin/env python3
"""Subtitle cues → audio/cues.json (for core/render/srt.py to write the .srt). Same rule as cueSpan() in index.html:
a cue starts when the voice-over line starts and ends at the end of the line + 0.45 s, or 0.08 s before the next line starts; each cue has two lines: Chinese on top, English below (one line each, no wrapping)."""
import json, os
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tl = json.load(open(f'{D}/timeline.json', encoding='utf-8')); vd = json.load(open(f'{D}/audio/vo/dur.json'))
vo = tl['vo']; out = []
for i, v in enumerate(vo):
    t1 = v['t'] + vd.get(v['id'], 2.5) + .45
    if i + 1 < len(vo): t1 = min(t1, vo[i + 1]['t'] - .08)
    out.append({'t0': v['t'], 't1': round(t1, 3), 'text': v['zh'] + '\n' + v['text']})
json.dump(out, open(f'{D}/audio/cues.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for c in out: print(f"{c['t0']:6.2f}–{c['t1']:6.2f}  {c['t1'] - c['t0']:.2f}s  {c['text'].replace(chr(10), ' | ')}")

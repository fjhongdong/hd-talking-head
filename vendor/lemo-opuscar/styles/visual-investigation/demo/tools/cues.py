#!/usr/bin/env python3
"""Subtitles from film.json → audio/cues.json (the input for core/render/srt.py): one Chinese line and one English line per cue."""
import json, os
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = json.load(open(os.path.join(D, 'film.json'), encoding='utf-8'))
json.dump([{'t0': a, 't1': b, 'text': f'{zh}\n{en}'} for a, b, zh, en in F['subs']], open(os.path.join(D, 'audio/cues.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(F['subs']), 'cues')

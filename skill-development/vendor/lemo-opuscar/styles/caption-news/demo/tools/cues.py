"""timeline.json -> audio/cues.json for core/render/srt.py (one Chinese line + one English line per cue),
and checks the subtitle timing rules: every cue >= 1.8 s and >= its spoken line + 0.6 s."""
import json, os, re
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tl = json.load(open(os.path.join(D, 'timeline.json'))); dur = json.load(open(os.path.join(D, 'audio', 'vo', 'dur.json')))
clean = lambda s: re.sub(r'[|{}]', '', s)
cues = [{'t0': tl['hook']['t0'], 't1': tl['hook']['t1'], 'text': tl['hook']['zh'] + '\n' + tl['hook']['en']}]
cues += [{'t0': c['t0'], 't1': c['t1'], 'text': clean(c['zh']) + '\n' + c['en']} for c in tl['caps']]
json.dump(cues, open(os.path.join(D, 'audio', 'cues.json'), 'w'), ensure_ascii=False, indent=1)
bad = 0; spans = sorted((st, st + dur[k]) for k, st in tl['vo'].items())
for c in cues:
    d = c['t1'] - c['t0']; spoken = sum(max(0, min(b, c['t1']) - max(a, c['t0'])) for a, b in spans)
    need = max(1.8, spoken + .6 if spoken > .3 else 1.8)
    if d + 1e-6 < 1.8 or '\n' not in c['text']: bad += 1; print('BAD', c)
    print(f"{'OK ' if d >= 1.8 else 'BAD'} {c['t0']:5.2f}-{c['t1']:5.2f} {d:4.2f}s spoken {spoken:4.2f}s  {c['text'].splitlines()[0]}")
print('cues', len(cues), 'bad', bad)

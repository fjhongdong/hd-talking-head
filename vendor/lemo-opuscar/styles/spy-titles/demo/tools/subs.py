# Subtitle export: same formula as film.js subs() (t0 = narration start, t1 = t0 + max(1.8, speech + 0.6)) → out/subs.json
import json, os
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.dirname(H)
L = json.load(open(os.path.join(D, 'lines.json'))); d = json.load(open(os.path.join(D, 'voices', 'dur.json')))
os.makedirs(os.path.join(D, 'out'), exist_ok=True)
json.dump([{'t0': l['t'], 't1': round(l['t'] + max(1.8, d[l['id']] + .6), 3), 'text': l['text']} for l in L], open(os.path.join(D, 'out', 'subs.json'), 'w'), indent=1)
print('subs', len(L))

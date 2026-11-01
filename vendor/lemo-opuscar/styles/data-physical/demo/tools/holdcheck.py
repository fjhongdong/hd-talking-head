"""Comparison hold check: once each comparison's readouts (the 2014 pair, the 2020/2021 pairs) are fully in frame, they must hold at least 2.5 s before the verdict appears.
Reading readcheck's per-frame text log is awkward, so this uses the timeline's time points directly (in the picture code, readouts and verdicts are driven by these time points)."""
import json, os, sys
d = sys.argv[1]; T = json.load(open(os.path.join(d, 'out/timeline.json')))['T']
ok = True
for name, hold0, verdict in (('2014 wind vs solar', T['hold14'][0] + .35, T['verdict14']), ('2020/2021 four readings', T['hold21'][0] + .35, T['verdict21'])):
    h = verdict - hold0; ok &= h >= 2.5
    print(f"{'OK  ' if h >= 2.5 else 'SHORT'} {name}: readings fully in from {hold0:.2f} s, verdict at {verdict:.2f} s, held {h:.2f} s")
sys.exit(0 if ok else 1)

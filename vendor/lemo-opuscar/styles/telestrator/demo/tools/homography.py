#!/usr/bin/env python3
"""Pitch lines → perspective matrix. In pitch.json each shot gives ≥4 known pitch points (metres, origin = centre of the goal, x = distance out from the goal line,
y = across the pitch, negative on the far side) and their positions in the 1920×1080 frame; writes assets/pitch.json: each shot's H (pitch → frame),
the residuals, and the pitch coordinates of the points to convert (the shot's strike point). The page uses H to "flatten the frame into a top-down view"."""
import json, os, sys
import numpy as np
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = json.load(open(f'{D}/tools/pitch.json'))
def dlt(P, Q):
    A = []
    for (x, y), (u, v) in zip(P, Q):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u]); A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, Vt = np.linalg.svd(np.array(A, float)); H = Vt[-1].reshape(3, 3); return H / H[2, 2]
def app(H, p):
    q = H @ np.array([p[0], p[1], 1.0]); return q[:2] / q[2]
out = {}
for shot, s in src.items():
    P = [c[0] for c in s['pts']]; Q = [c[1] for c in s['pts']]
    H = dlt(P, Q); Hi = np.linalg.inv(H)
    res = [float(np.hypot(*(app(H, p) - np.array(q)))) for p, q in zip(P, Q)]
    marks = {k: [round(float(v), 2) for v in app(Hi, xy)] for k, xy in s.get('marks', {}).items()}
    out[shot] = {'H': (H / H[2, 2]).round(9).tolist(), 'res_px': [round(r, 1) for r in res], 'marks_m': marks}
    print(shot, 'residual px', [round(r, 1) for r in res])
    for k, m in marks.items(): print(f'   {k}: x={m[0]} m out, y={m[1]} m, dist to goal centre {np.hypot(*m):.1f} m')
os.makedirs(f'{D}/assets', exist_ok=True)
json.dump(out, open(f'{D}/assets/pitch.json', 'w'), indent=1)

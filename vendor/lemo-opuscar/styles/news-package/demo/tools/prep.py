"""assets/plates/ + raw/ → assets/：the illustrative plates get one shared grade (cool duotone); the Europe map is decoded and projected into 2D paths.
The plates' source files assets/plates/plate_*.jpg are committed with the repo (AI-generated, see CREDITS); a missing image exits with an error.
Run with the library's .venv:$LIB/.venv/bin/python tools/prep.py"""
import json, math, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW, PLATES, OUT = os.path.join(HERE, 'raw'), os.path.join(HERE, 'assets', 'plates'), os.path.join(HERE, 'assets')
os.makedirs(OUT, exist_ok=True)

# —— Shared grade: every picture-layer asset goes through the same curve (brand black → off-white) ——
SHADOW = np.array([14, 16, 19], float)     # #0E1013, a little deeper than brand black #121417
LIGHT = np.array([236, 231, 216], float)   # #ECE7D8, brand off-white #F4F1E8 pulled down one step
def grade(im, black=8, white=232, gamma=1.05):
    g = np.asarray(im.convert('L'), float)
    lo, hi = np.percentile(g, 0.5), np.percentile(g, 99.6)
    g = np.clip((g - lo) / max(1, hi - lo), 0, 1) ** gamma
    g = g * g * (3 - 2 * g) * .35 + g * .65
    g = black / 255 + g * (white - black) / 255
    rgb = SHADOW[None, None] + (LIGHT - SHADOW)[None, None] * g[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))

meta = {}
for name, crop in [('datacenter', None), ('wafer', None)]:
    src = os.path.join(PLATES, f'plate_{name}.jpg')
    if not os.path.exists(src):
        sys.exit(f'missing plate: {src} (generate it with tools/gen_plates.sh or put your own image there; STYLE.md §10)')
    im = Image.open(src).convert('RGB')
    if crop: im = im.crop(crop)
    grade(im).save(os.path.join(OUT, f'plate_{name}.jpg'), quality=92)
    meta[name] = im.size

# —— Europe map: world-atlas countries-50m (Natural Earth, public domain) → Lambert azimuthal equal-area projection (centre 10°E 52°N, same idea as EPSG:3035) ——
topo = json.load(open(os.path.join(RAW, 'countries-50m.json')))
sx, sy = topo['transform']['scale']; tx, ty = topo['transform']['translate']
arcs = []
for a in topo['arcs']:
    x = y = 0; pts = []
    for dx, dy in a:
        x += dx; y += dy; pts.append((x * sx + tx, y * sy + ty))
    arcs.append(pts)
L0, P0 = math.radians(10), math.radians(52)
def laea(lon, lat):
    l, p = math.radians(lon), math.radians(lat)
    k = math.sqrt(2 / (1 + math.sin(P0) * math.sin(p) + math.cos(P0) * math.cos(p) * math.cos(l - L0)))
    x = k * math.cos(p) * math.sin(l - L0)
    y = k * (math.cos(P0) * math.sin(p) - math.sin(P0) * math.cos(p) * math.cos(l - L0))
    return round(x * 6371, 1), round(-y * 6371, 1)          # km, y points down
def ring(r):
    pts = []
    for i in r:
        s = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts += s if not pts else s[1:]
    return pts
EU27 = {'040', '056', '100', '191', '196', '203', '208', '233', '246', '250', '276', '300', '348', '372', '380', '428', '440', '442',
        '470', '528', '616', '620', '642', '703', '705', '724', '752'}
WIN = (-32, 25, 60, 75)  # lon/lat window: keep only countries that intersect the Europe window; ring points outside the window are clamped to its edge
countries = {}
for g in topo['objects']['countries']['geometries']:
    if 'arcs' not in g: continue
    polys = g['arcs'] if g['type'] == 'MultiPolygon' else [g['arcs']]
    rings = []
    for p in polys:
        for r in p:
            pts = ring(r)
            if not any(WIN[0] <= x <= WIN[2] and WIN[1] <= y <= WIN[3] for x, y in pts): continue
            pts = [(min(max(x, WIN[0] - 8), WIN[2] + 8), min(max(y, WIN[1] - 6), WIN[3] + 6)) for x, y in pts]
            rings.append([laea(x, y) for x, y in pts])
    if rings:
        countries[g.get('id', g['properties']['name'])] = {'name': g['properties']['name'], 'eu': g.get('id') in EU27, 'rings': rings}
DUBLIN = laea(-6.2603, 53.3498)
json.dump({'countries': countries, 'dublin': DUBLIN, 'brussels': laea(4.3517, 50.8503)}, open(os.path.join(OUT, 'europe.json'), 'w'), separators=(',', ':'))

json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'), indent=1)
print(meta, len(countries), 'countries; Dublin', DUBLIN, 'EU', sum(c['eu'] for c in countries.values()))

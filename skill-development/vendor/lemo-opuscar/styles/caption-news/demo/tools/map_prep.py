"""US lower-48 states from Natural Earth (public domain) -> projected polygons for the map shot.
Albers equal-area conic (standard parallels 29.5 / 45.5 N, centre 96 W / 37.5 N), scaled to a 1000-unit-wide box.
python3 tools/map_prep.py <ne_110m_admin_1_states_provinces.geojson> <out.json>"""
import json, math, sys
src, out = sys.argv[1], sys.argv[2]
d = json.load(open(src))
p1, p2, l0, f0 = map(math.radians, (29.5, 45.5, -96.0, 37.5))
n = (math.sin(p1) + math.sin(p2)) / 2; C = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
r0 = math.sqrt(C - 2 * n * math.sin(f0)) / n
def proj(lon, lat):
    lon, lat = math.radians(lon), math.radians(lat)
    r = math.sqrt(C - 2 * n * math.sin(lat)) / n; th = n * (lon - l0)
    return r * math.sin(th), r0 - r * math.cos(th)
states = []
for f in d['features']:
    p = f['properties']; name = p['name']
    if name in ('Alaska', 'Hawaii'): continue
    g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    rings = [[proj(*pt) for pt in poly[0]] for poly in polys]
    states.append({'name': name, 'postal': p.get('postal'), 'rings': rings})
xs = [x for s in states for r in s['rings'] for x, _ in r]; ys = [y for s in states for r in s['rings'] for _, y in r]
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); k = 1000 / (x1 - x0)
for s in states:
    s['rings'] = [[[round((x - x0) * k, 1), round((y1 - y) * k, 1)] for x, y in r] for r in s['rings']]
    pts = [pt for r in s['rings'] for pt in r]
    s['c'] = [round(sum(p[0] for p in pts) / len(pts), 1), round(sum(p[1] for p in pts) / len(pts), 1)]
json.dump({'w': 1000, 'h': round((y1 - y0) * k, 1), 'states': states}, open(out, 'w'))
print(out, len(states), 'states, box 1000 x', round((y1 - y0) * k, 1))

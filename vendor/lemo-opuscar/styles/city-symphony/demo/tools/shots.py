"""Shot list (all timings come from timeline.bar).

CLIPS: the video clips prep.py cuts → work/clips/<id>.mp4 (frames = length × 30, frame-accurate)
  id: dict(src, s0=source in-point s, n=frame count, speed=constant or [(seconds into clip, speed), …] keyframes (smooth interpolation = speed ramp),
           blend=max frames blended (360° shutter, light rivers), interp=motion-compensated interpolation factor for slow motion, size=output size)
  speed = source seconds / film seconds.

SHOTS: shots on the timeline (render.py composites them frame by frame)
  kind: clip / photo / flicker (two clips alternating every 2 frames)/ grid / split / flash / page / black
"""
from timeline import bar, FPS, NOON, GRID, BRAKE, DUSK, FLASH, STOP, PAGE, CARD, DUR

V = dict(sky='raw/sky23.webm', nyim='raw/nyim.webm', b99='raw/br1899.mp4',
         empty='raw/empty.mp4', pcm='raw/pcm.webm', cav='raw/cav.webm', mbn='raw/mbn.ogv', fw='raw/fw16.mp4',
         kel='raw/kel.mp4', sun='raw/sunfox.mp4', earth='raw/earth.webm')
NIGHT_SRC = ('kel', 'sun', 'earth')      # night sources: stronger bloom


def nf(a, b):
    return round(b * FPS) - round(a * FPS)


CLIPS = {}
SHOTS = []


def clip(cid, t_in, t_out, src, s0, speed, blend=1, interp=1, motion=(1, 1, 0, 0), wb=.3, fx=None, size=(1920, 1080)):
    CLIPS[cid] = dict(src=src, s0=s0, n=nf(t_in, t_out), speed=speed, blend=blend, interp=interp, size=size)
    SHOTS.append(dict(id=cid, kind='clip', t0=t_in, t1=t_out, motion=motion, wb=wb, fx=fx, src=src))


def photo(sid, t_in, t_out, names, c, s0, s1, drift=(0, 0), wb=.3, expo=1.0):
    SHOTS.append(dict(id=sid, kind='photo', t0=t_in, t1=t_out, names=names, c=c, s=(s0, s1), drift=drift, wb=wb, expo=expo))


# ───────── night → morning (0–8 s)─────────
photo('s01_orbit', 0.0, bar(2), ['iss47'], (.585, .50), 1.25, 1.95, wb=0)          # fall from orbit into the city (title)
clip('s02_sky_dawn', bar(2), bar(3), 'sky', 250.0, 40, blend=30, wb=0, motion=(1.0, 1.06, 0, -8))  # night → dawn light river
clip('s03_air_park', bar(3), bar(3, 2), 'empty', 1.0, 3, blend=3, wb=.3, motion=(1.04, 1.0, 0, 0))   # early morning, aerial of Bethesda Terrace in Central Park
clip('s04_gc_clock', bar(3, 2), bar(3, 3), 'nyim', 1.0, 1, motion=(1.0, 1.04, 0, 0), wb=.5)
photo('s05_ph_clock', bar(3, 3), bar(4), ['ph_clock'], (.5, .36), 1.0, 1.05, wb=.3)   # clock → clock (circle match cut)

# ───────── morning (8–16 s)─────────
clip('s06_oc_corr', bar(4), bar(4, 2), 'nyim', 77.8, [(0, 1.0), (.6, 6.0), (1.0, 6.0)], blend=6, motion=(1.0, 1.06, 0, 0), wb=.5)   # speed ramp 1×→6×
clip('s07_air_top', bar(4, 2), bar(5), 'pcm', 61.0, 2, blend=2, wb=.25)                       # top-down: crowds on Central Park West
clip('s08_oculus', bar(5), bar(6), 'nyim', 87.3, 2.1, blend=3, wb=.45, fx='trails')   # crowd → light trails
MONT = [('s09_street', 'nyim', 56.2, 2), ('s10_tunnel', 'cav', 4.5, 3), ('s11_fifth', 'nyim', 52.2, 2), ('s12_mbridge', 'mbn', 1.0, 3),
        ('s13_wash', 'nyim', 47.2, 2), ('s14_harbor', 'fw', 30.5, 2), ('s15_chrysler', 'nyim', 59.6, 1.2), ('s16_viaduct', 'cav', 12.5, 3),
        ('s16b_flags', 'empty', 9.0, 3), ('s16c_liberty', 'nyim', 99.6, 2), ('s16d_tower', 'cav', 88.0, 3), ('s16e_stairs', 'nyim', 82.4, 2)]
for k, (cid, src, s0, sp) in enumerate(MONT):     # bar 6 cuts every beat (4 cuts), bar 7 every half beat (8 cuts)
    a, b = (bar(6, k), bar(6, k + 1)) if k < 4 else (bar(7, (k - 4) * .5), bar(7, (k - 4) * .5 + .5))
    clip(cid, a, b, src, s0, sp, blend=max(1, round(sp)), wb=.4 if src == 'nyim' else .25)

# ───────── noon + grid (16–24 s)─────────
clip('s17_sky_noon', NOON, GRID, 'sky', 548.0, 37.5, blend=24, wb=.25, motion=(1.0, 1.05, 0, 0))   # cloud river + 8,804,190
SHOTS.append(dict(id='s18_grid', kind='grid', t0=GRID, t1=BRAKE))
# grid pool: 1 s (30 frames) per clip, all daytime
POOL = [('g_air_cpw', 'pcm', 52.5, 2), ('g_oculus', 'nyim', 88.4, 2), ('g_harbor', 'fw', 31.0, 2), ('g_sky', 'sky', 620.0, 40),
        ('g_oc_corr', 'nyim', 80.2, 2), ('g_mbridge', 'mbn', 8.5, 3), ('g_street2', 'nyim', 57.0, 2), ('g_ferry', 'nyim', 95.5, 2),
        ('g_air_top', 'pcm', 64.0, 3), ('g_wash2', 'nyim', 48.2, 2), ('g_mbdrive', 'cav', 108.9, 2), ('g_clock2', 'nyim', 0.0, 1),
        ('g_rock', 'nyim', 70.0, 2), ('g_radio', 'empty', 29.0, 2), ('g_chrysler2', 'nyim', 60.4, 1.2), ('g_esb', 'fw', 87.95, .9)]
for cid, src, s0, sp in POOL:
    CLIPS[cid] = dict(src=src, s0=s0, n=30, speed=sp, blend=max(1, round(sp)) if src != 'sky' else 24, interp=1, size=(1920, 1080))
GRID_STAGES = [   # (start, columns, rows, shots in the pool)
    (GRID, 2, 1, ['g_air_cpw', 'g_oculus']),
    (bar(10, 2), 2, 2, ['g_harbor', 'g_sky', 'g_oc_corr', 'g_mbridge']),
    (bar(11), 3, 3, ['g_street2', 'g_air_top', 'g_ferry', 'g_wash2', 'g_sky', 'g_mbdrive', 'g_clock2', 'g_oculus', 'g_rock']),
    (bar(11, 2), 4, 4, [c[0] for c in POOL]),
]

# ───────── brake (24–32 s)─────────
clip('s19_bubble', BRAKE, bar(13, 2), 'nyim', 41.75, [(0, 2.2), (.55, .3), (3.0, .3)], interp=3, wb=.45, motion=(1.0, 1.08, 0, -10))  # speed ramp into slow motion
CLIPS['b_1899'] = dict(src='b99', s0=3.4, n=nf(bar(13, 2), bar(15, 2)), speed=.75, blend=1, interp=1, mix=True, size=(1440, 1080))
CLIPS['b_today'] = dict(src='nyim', s0=105.15, n=nf(bar(13, 2), bar(15, 2)), speed=.72, blend=1, interp=1, mix=True, size=(1920, 1080))
SHOTS.append(dict(id='s20_split', kind='split', t0=bar(13, 2), t1=bar(15, 2), left='b_1899', right='b_today'))
photo('s21_ph_gct', bar(15, 2), DUSK, ['ph_gct'], (.5, .62), 1.10, 1.16, wb=.35)       # long exposure: people reduced to ghosts

# ───────── dusk → night (32–40 s)─────────
clip('s22_bridge_sun', DUSK, bar(16, 2), 'nyim', 108.4, 3, blend=3, wb=.35, motion=(1.0, 1.04, 0, 0))
clip('s23_ferry', bar(16, 2), bar(16, 3), 'nyim', 93.2, 2, blend=2, wb=.35)
clip('s24_dusk_street', bar(16, 3), bar(17), 'cav', 104.5, 3, blend=3, wb=.2)               # pink sunset at the end of an empty street
clip('s25_sky_dusk', bar(17), bar(17, 2), 'sky', 716.0, 75, blend=30, wb=0)              # night falls in one second
CLIPS['fl_day'] = dict(src='sky', s0=600.0, n=15, speed=30, blend=24, interp=1, size=(1920, 1080))
CLIPS['fl_night'] = dict(src='sky', s0=880.0, n=15, speed=30, blend=24, interp=1, size=(1920, 1080))
SHOTS.append(dict(id='s26_flicker', kind='flicker', t0=bar(17, 2), t1=bar(17, 3), a='fl_day', b='fl_night', wb=0))
photo('s27_ph_ts', bar(17, 3), bar(18), ['ph_ts1', 'ph_ts2'], (.5, .78), 1.0, 1.05, wb=.2)   # same-position photos alternating every 2 frames
clip('s28_tsq', bar(18), bar(18, 3), 'kel', 4.0, [(0, 1.0), (.7, 7.0), (1.5, 7.0)], blend=7, wb=0, motion=(1.0, 1.08, 0, 0))   # 42nd Street overhead time-lapse + 220,000
clip('s29_tsq2', bar(18, 3), bar(19), 'sun', .3, 3, blend=3, wb=0)                     # Times Square TKTS steps, night
clip('s30_top', bar(19), bar(19, 2), 'kel', 17.0, 5, blend=14, wb=0)   # traffic → lines of light (high blend count)
clip('s31_top2', bar(19, 2), bar(19, 3), 'earth', 84.25, 3, blend=3, wb=0, motion=(1.0, 1.04, 0, 0))   # Times Square from above at night
clip('s32_tsq3', bar(19, 3), FLASH, 'sun', 2.5, 6, blend=6, wb=0)

# ───────── the day flashes back in reverse (40–42 s = 60 frames), hard stop ─────────
SHOTS.append(dict(id='s33_flash', kind='flash', t0=FLASH, t1=STOP))
FLASH_SRC = ['s32_tsq3', 's30_top', 's28_tsq', 's27_ph_ts', 's25_sky_dusk', 's24_dusk_street', 's22_bridge_sun', 's21_ph_gct',
             's19_bubble', 's17_sky_noon', 's15_chrysler', 's12_mbridge', 's10_tunnel', 's08_oculus', 's07_air_top',
             's06_oc_corr', 's05_ph_clock', 's04_gc_clock', 's03_air_park', 's02_sky_dawn', 's01_orbit', 's02_sky_dawn']
FLASH_LEN = [4] * 8 + [2] * 14
assert sum(FLASH_LEN) == nf(FLASH, STOP)

SHOTS.append(dict(id='s34_black', kind='black', t0=STOP, t1=PAGE))
SHOTS.append(dict(id='s35_page', kind='page', t0=PAGE, t1=CARD))
# coda: same camera position, the next day's dawn (night → blue → early morning), quotation over it; at the end slate it is darkened and keeps running
clip('s36_dawn', CARD, DUR, 'sky', 1008.0, 8, blend=8, wb=0, motion=(1.0, 1.06, 0, -6))

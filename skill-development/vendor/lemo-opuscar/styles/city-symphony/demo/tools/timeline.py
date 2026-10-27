"""Beat map: the single source of timing for music and picture. 120 BPM, T0 = 0, 1 bar = 4 beats = 2 s, 30 fps (1 beat = 15 frames, triplet = 5 frames).
To change the music: change BPM / T0 and align BRAKE / DUSK / STOP to the new track's breakdown, restart and cut-off; all lengths in shots.py are computed by bar()."""
BPM = 120
BEAT = 60 / BPM          # 0.5 s
BAR = 4 * BEAT           # 2.0 s
T0 = 0.0                 # first beat = first frame: full organ slams in at 0.0 s
FPS = 30


def bar(n, beat=0.0):
    """Time (seconds) of beat `beat` in bar n (counting from 0)"""
    return T0 + n * BAR + beat * BEAT


# sections (in bars): musical texture density = cutting density
NIGHT = bar(0)     # 0–3   night → morning: eighth-note arpeggios; 4 s → 2 s → 1 s → half beat
MORNING = bar(4)   # 4–7   triplets against eighths + staccato woodwinds; 1 beat → half beat
NOON = bar(8)      # 8–9   noon cloud river + population figure (one 4 s long take)
GRID = bar(10)     # 10–11 grid: 1×2 → 2×2 → 3×3 → 4×4, sixteenths
BRAKE = bar(12)    # 12–15 brake: arpeggios all stop (soap bubbles / 1899 split screen / long exposure)
DUSK = bar(16)     # 16–19 dusk → night: eighths → triplets → sixteenths
FLASH = bar(20)    # 20    the day flashes back in reverse: 4 frames → 2 frames
STOP = bar(21)     # 42.0  hard stop: dry signal cut, black
PAGE = bar(21, .6)   # 42.3 book page (Leaves of Grass 1860, p.380)
CARD = bar(21, 2.5)  # 43.25 quotation over the last city shot (the next day's dawn)
SLATE = bar(23, 2.5) # 47.25 end slate (same shot, darkened, keeps running)
DUR = bar(26)        # 52.0

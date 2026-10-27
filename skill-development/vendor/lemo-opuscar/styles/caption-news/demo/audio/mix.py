"""Score + foley + voice + natural sound -> out/mix.wav and audio/stems/*.wav (48 kHz stereo).
Loudness is set to -14 LUFS later by core/render/mux.sh.
Reads: ../timeline.json (voice starts, silences, music hits), ../events.json (every on-screen action, from events.mjs),
audio/lines.json + audio/vo/*.wav (Kokoro), audio/src/swarm.wav (natural bee sound, CC BY 4.0).
Score: 120 BPM (beat 0.5 s, bar 2 s), A minor -> C major at the turn -> D minor threat -> A major at the verdict.
Instruments (sampled, core/audio/sampler.py): MuldjordKit drum kit, electric bass, marimba, vibraphone, glockenspiel,
trumpet / trombone staccato, horn, timpani, tubular bells, suspended cymbal, orchestral snare, claps, cellos spiccato."""
import json, os, sys
import numpy as np, soundfile as sf, soxr
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.dirname(H)
LIB = os.environ.get('LIB', os.path.abspath(os.path.join(D, '..', '..', '..')))
sys.path.insert(0, LIB); sys.path.insert(0, os.path.join(LIB, 'core', 'audio'))
from core.audio import sampler as S
import sfx
from sfx import SR, t_, env_exp, bp, lp, hp, noise, norm

TL = json.load(open(os.path.join(D, 'timeline.json')))
EV = json.load(open(os.path.join(D, 'events.json')))['ev']
DUR = TL['dur']; N = int(DUR * SR); BEAT = .5; S16 = .125
S.seed(7)

def buf(): return np.zeros((N, 2), np.float32)
def put(b, x, at, g=1.0, pan=0.0):
    i = int(round(at * SR)); x = np.asarray(x, np.float32)
    if i < 0: x = x[-i:]; i = 0
    if i >= N: return
    if x.ndim == 2:
        x = x[:max(0, N - i)]; b[i:i + len(x)] += x * g; return
    x = x[:max(0, N - i)]; l, r = np.sqrt(.5 * (1 - pan)), np.sqrt(.5 * (1 + pan))
    b[i:i + len(x), 0] += x * g * l * 1.414; b[i:i + len(x), 1] += x * g * r * 1.414

# ----------------------------------------------------------------- score (written as sampler events)
E = []
def n(t, inst, p, d, v, pan=0, g=1.0): E.append((t, inst, p, d, v, pan, g))
SIL = TL['music']['silences']
def silent(t): return any(a - 1e-6 <= t < b for a, b in SIL)

# chord map: (t0, t1, root midi for bass, chord tones for keys)
NOTE = {'A': 57, 'F': 53, 'C': 48, 'G': 55, 'D': 50, 'E': 52, 'Bb': 58}
CH = [
    (0.0, 2.0, 'A', 'm'), (2.0, 4.0, 'F', ''), (4.0, 5.0, 'G', ''),
    (5.0, 7.5, 'A', 'm'),
    (7.5, 9.5, 'A', 'm'), (9.5, 10.5, 'F', ''),
    (13.0, 15.0, 'C', ''), (15.0, 17.0, 'G', ''), (17.0, 19.0, 'A', 'm'), (19.0, 21.0, 'F', ''), (21.0, 23.0, 'C', ''),
    (23.0, 25.0, 'G', ''), (25.0, 27.0, 'A', 'm'), (27.0, 27.5, 'F', ''),
    (27.5, 30.0, 'F', ''), (30.0, 32.0, 'D', 'm'), (32.0, 34.0, 'A', 'm'), (34.0, 36.0, 'D', 'm'), (36.0, 37.5, 'E', ''),
    (37.5, 41.5, 'A', 'm'), (41.5, 45.5, 'A', 'm'),
    (45.5, 47.5, 'C', ''), (47.5, 49.5, 'G', ''), (49.5, 50.0, 'A', 'm'),
    (50.5, 52.5, 'A', ''), (52.5, 54.5, 'D', ''), (54.5, 59.5, 'A', ''),
]
def chord_at(t):
    for a, b, r, q in CH:
        if a <= t < b: return r, q
    return None
def tones(r, q, base=60):
    pc = NOTE[r] % 12; third = 3 if q == 'm' else 4
    return sorted(base + ((p - base) % 12) for p in (pc, pc + third, pc + 7))

def section(t):
    if t < 5.0: return 'A'
    if t < 7.5: return 'sting'
    if t < 10.5: return 'A'
    if t < 13.0: return 'sil'
    if t < 27.5: return 'B'
    if t < 30.0: return 'thin'
    if t < 37.5: return 'threat'
    if t < 41.5: return 'build'
    if t < 45.5: return 'map'
    if t < 50.0: return 'A2'
    if t < 50.5: return 'sil'
    if t < 54.5: return 'V'
    return 'end'

KIT = 'drum_kit'
t = 0.0
while t < DUR - 1e-6:
    sec = section(t); b16 = int(round(t / S16)); beat = b16 // 4; sub = b16 % 4; bar_beat = beat % 4
    ch = chord_at(t)
    if sec in ('A', 'A2', 'B', 'V'):
        if sub == 0: n(t, KIT, 'kick_drum_left', None, .78 if bar_beat in (0, 2) else .62, 0, .9)
        if sub == 0 and bar_beat in (1, 3) and t >= 2.0: n(t, KIT, 'snare_1', None, .66, .05, .7)
        if sub == 2: n(t, KIT, 'hi_hat_closed', None, .55, .25, .45)
        if sec in ('B', 'V') and sub in (1, 3): n(t, KIT, 'hi_hat_closed', None, .3, .25, .3)
        if sec == 'B' and sub == 0 and bar_beat in (1, 3): n(t, 'claps', 'group', None, .5, -.1, .35)
        if ch and sub in (0, 2):   # eighth-note bass, octave pop on the last eighth of each beat pair
            r, q = ch; m = NOTE[r] - 24 + (12 if (b16 // 2) % 4 == 3 else 0)
            n(t, 'electric_bass', m, .22, .72, 0, .95)
        if ch and sec in ('A', 'A2') and t >= .5:   # marimba sixteenth ostinato: the hive's busy hum
            tn = tones(*ch, base=69); m = tn[[0, 1, 2, 1][sub]] + (12 if (beat % 2 and sub == 2) else 0)
            n(t, 'marimba', m, .12, .42 if sub == 0 else .3, .35, .38)
        if ch and sec in ('B', 'V') and sub == 2 and bar_beat in (0, 2):   # vibraphone off-beat chords
            for m in tones(*ch, base=64): n(t, 'vibraphone', m, .4, .38, -.3, .38)
    elif sec == 'sting':
        if abs(t - 5.0) < 1e-6 or abs(t - 6.0) < 1e-6 or abs(t - 6.5) < 1e-6:
            for m in (69, 72, 76): n(t, 'trumpet_stac', m, .25, .8, .2, .55)
            for m in (45, 52): n(t, 'trombone_stac', m, .3, .8, -.2, .6)
        if sub == 0 and bar_beat in (0, 2): n(t, KIT, 'kick_drum_left', None, .8, 0, .9)
        if sub == 0: n(t, KIT, 'tom_3' if bar_beat % 2 else 'tom_2', None, .55, -.2, .45)
        if sub == 2: n(t, KIT, 'hi_hat_closed', None, .45, .25, .35)
        if sub in (0, 2): n(t, 'electric_bass', NOTE['A'] - 24, .22, .7, 0, .9)
    elif sec == 'thin':
        if sub == 0 and bar_beat == 0: n(t, KIT, 'kick_drum_left', None, .7, 0, .85)
        if sub == 0: n(t, 'cellos_spic', 41 if t < 29.0 else 40, .2, .5, -.2, .5)
        if sub == 2: n(t, 'contrabass_pizz', 29 if t < 29.0 else 28, .3, .5, .1, .5)
    elif sec == 'threat':   # half time
        if sub == 0 and bar_beat == 0: n(t, KIT, 'kick_drum_left', None, .85, 0, .95)
        if sub == 0 and bar_beat == 2: n(t, KIT, 'snare_1', None, .72, .05, .75)
        if sub == 2 and bar_beat == 3: n(t, KIT, 'kick_drum_left', None, .55, 0, .7)
        if sub == 2: n(t, KIT, 'hi_hat_closed', None, .35, .25, .3)
        if ch and sub in (0, 2):
            r, q = ch; n(t, 'cellos_spic', NOTE[r] - 12, .2, .55, -.25, .55)
        if ch and sub == 0 and bar_beat == 0: n(t, 'electric_bass', NOTE[ch[0]] - 24, 1.8, .7, 0, .9)
    elif sec == 'build':
        if sub == 0: n(t, KIT, 'kick_drum_left', None, .7, 0, .85)
        rate = 2 if t < 38.75 else 1
        if t < 39.75 and b16 % rate == 0: n(t, 'snare', 'on', None, .3 + .5 * (t - 37.5) / 2.25, .05, .5)
        if sub in (0, 2): n(t, 'electric_bass', NOTE['A'] - 24, .2, .65, 0, .85)
        if t >= 39.75 and sub == 0: n(t, 'cellos_spic', 45, .2, .45, -.2, .4)
    elif sec == 'map':
        if sub == 0 and bar_beat in (0, 2): n(t, KIT, 'kick_drum_left', None, .75, 0, .85)
        if t >= 42.5: n(t, KIT, ['tom_4', 'tom_4', 'tom_3', 'tom_4'][sub], None, .3 + .25 * min(1, (t - 42.5) / 2.4), -.15, .45)
        if sub in (0, 2): n(t, 'electric_bass', NOTE['A'] - 24, .2, .65, 0, .85)
        if sub == 0: n(t, 'marimba', [69, 72, 76, 72][bar_beat], .2, .35, .35, .4)
    t = round(t + S16, 6)

# structural hits
def brass_chord(t, ms_tp, ms_tb, v=.85, horn=None):
    for m in ms_tp: n(t, 'trumpet_stac', m, .3, v, .2, .55)
    for m in ms_tb: n(t, 'trombone_stac', m, .35, v, -.2, .6)
    if horn:
        for m in horn: n(t, 'horn', m, horn_d, .6, 0, .45)
horn_d = 1.6
# hook (0.13): timpani + bass drum + crash
n(.13, 'timpani', 'A2', 1.5, .9, 0, .9); n(.13, 'bass_drum', None, None, .9, 0, .8); n(.13, KIT, 'crash_left', None, .7, .3, .5)
# sting (5.0)
n(5.0, KIT, 'crash_right', None, .8, -.3, .55); n(5.0, 'timpani', 'D2', 1.5, .9, 0, .8)
n(7.0, 'snare', 'roll', .5, .55, .05, .6)
# silence 1 ends with a suspended-cymbal swell into the turn
n(12.15, 'sus_cymbal', 'cresc', .85, .6, .2, .55)
# the turn (13.0): C major
brass_chord(13.0, (72, 76, 79), (48, 55)); n(13.0, KIT, 'crash_left', None, .85, .3, .6); n(13.0, 'glockenspiel', 84, .6, .6, .3, .45)
# chart breath (16–19): glockenspiel motif over the groove
for i, m in enumerate((76, 79, 84, 83, 79, 76, 74, 76)): n(16.0 + i * .375, 'glockenspiel', m, .3, .45, .3, .35)
# split counters settle (20.95) / grid lights (23.78, 24.82, 25.96)
for tt, m in ((20.95, 84), (23.78, 79), (24.82, 83), (25.96, 86)): n(tt, 'glockenspiel', m, .4, .5, .3, .35)
# the mite (30.6): low brass, timpani, toms
n(30.6, 'timpani', 'D2', 1.5, 1.0, 0, .95); n(30.6, 'bass_drum', None, None, .95, 0, .85)
for m in (38, 45): n(30.6, 'trombone_stac', m, .5, .9, -.2, .65)
n(30.0, 'sus_cymbal', 'cresc', .6, .45, .2, .4)
# the spike (39.75): crash + dissonant brass (Bb over A)
n(39.75, KIT, 'crash_right', None, .85, -.3, .6); brass_chord(39.75, (70, 74, 77), (46, 53), .9); n(39.75, 'timpani', 'A2', 1.5, .9, 0, .8)
# map push: cymbal swell into the mask transition (44.9)
n(43.6, 'sus_cymbal', 'cresc', 1.3, .6, .2, .5); n(44.9, KIT, 'crash_left', None, .7, .3, .5)
n(45.5, 'glockenspiel', 84, .5, .5, .3, .35); n(49.0, 'glockenspiel', 88, .6, .55, .3, .4)
# silence 2 swell, verdict (50.5): A major
n(50.1, 'sus_cymbal', 'cresc', .4, .5, .2, .45)
horn_d = 2.0
brass_chord(50.5, (69, 73, 76), (45, 52), .9, horn=(57, 61, 64)); n(50.5, 'timpani', 'A2', 1.5, 1.0, 0, .9)
n(50.5, KIT, 'crash_left', None, .9, .3, .6); n(50.5, 'tubular_bells', 69, 3.0, .6, .2, .45)
n(52.5, 'tubular_bells', 74, 2.0, .45, .2, .35)
# end card (54.5): last hit, held horns, glockenspiel A–C#–E–A
horn_d = 4.6
brass_chord(54.5, (69, 73, 76), (45, 52), .8, horn=(57, 61, 64, 69)); n(54.5, 'timpani', 'A2', 1.5, .85, 0, .8)
n(54.5, KIT, 'crash_right', None, .7, -.3, .5); n(54.5, 'tubular_bells', 81, 4.5, .5, .2, .35)
for i, m in enumerate((81, 85, 88, 93)): n(55.0 + i * .5, 'glockenspiel', m, .8, .42, .3, .3)
n(54.5, 'contrabass', 33, 4.6, .45, 0, .45)

E = [e for e in E if not (silent(e[0]) and e[1] not in ('sus_cymbal',))]
mus = S.render(E, dur=DUR, master=False).astype(np.float32)
mus = S.room(mus, size=.32, mix=.12)
# hard stops into the silences (the cut is the effect), and a fade at the very end
for a, b in SIL:
    i0, i1 = int(a * SR), int(b * SR); g = np.ones(N, np.float32)
    g[i0:i1] = 0; ramp = int(.012 * SR); g[i0:i0 + ramp] = np.linspace(1, 0, ramp)
    # keep the swell that leads out of each silence
    sw0 = int((b - (.85 if b == 13.0 else .4)) * SR); g[sw0:i1] = np.linspace(0, 1, i1 - sw0) ** 2
    mus *= g[:, None]
fade = np.ones(N, np.float32); f0 = int((DUR - 1.4) * SR); fade[f0:] = np.linspace(1, 0, N - f0) ** 1.5; mus *= fade[:, None]

# ----------------------------------------------------------------- voice
vo = buf(); lines = {l['id']: l for l in json.load(open(os.path.join(H, 'lines.json')))}
for k, st in TL['vo'].items():
    x, sr = sf.read(os.path.join(H, 'vo', k + '.wav'), dtype='float32')
    if x.ndim > 1: x = x.mean(1)
    x = soxr.resample(x, sr, SR); x = hp(x, 90)
    x = sfx.compress(x, thr=.18, ratio=3.0); x = x / (np.sqrt(np.mean(x[np.abs(x) > .01] ** 2)) + 1e-9) * .12
    put(vo, x, st, 1.0, 0)

# ----------------------------------------------------------------- foley from the page's events
fx = buf(); rng = np.random.default_rng(3)
def tick(p=1.0, v=1.0): return sfx.click(p, v) * .6
def squeak(d):   # highlighter / marker on paper
    tt = t_(d); x = bp(noise(d), 1800, 5200) * (.6 + .4 * np.sin(2 * np.pi * 9 * tt)) * np.minimum(1, tt / .02) * np.minimum(1, (d - tt) / .03 + .01)
    return norm(x) * .5
def paper(d=.45): tt = t_(d); return norm(bp(noise(d), 500, 6000) * np.exp(-tt / .12) * (1 + .6 * np.sin(2 * np.pi * 23 * tt))) * .6
def riser(d):
    tt = t_(d); x = noise(d); y = np.zeros_like(x)
    for i in range(8):
        a, b = int(i * len(x) / 8), int((i + 1) * len(x) / 8); f = 400 * 2 ** (i * .6); y[a:b] = bp(x, f, f * 2.2)[a:b]
    return norm(y * (tt / d) ** 2) * .7
def shutter(): return norm(np.concatenate([sfx.click(.7, 1), np.zeros(int(.045 * SR)), sfx.click(.55, .8)])) * .8
for e in EV:
    t, ty = e['t'], e['type']
    if ty == 'slam': put(fx, sfx.click(.8, .7) * .3 + 0, t, .5 * e.get('big', 1), 0); put(fx, sfx.thump(.6, 90), t, .35 * e.get('big', 1))
    elif ty == 'hook': put(fx, sfx.thump(1.0, 55), t, .9); put(fx, sfx.whoosh(.25), t - .2, .35)
    elif ty == 'rattle':
        k = 0
        while k * .045 < e['d']: put(fx, tick(1.2 + .3 * rng.random(), .6), t + k * .045, .22, rng.uniform(-.3, .3)); k += 1
    elif ty == 'whoosh': put(fx, sfx.whoosh(.32), t - .24, .45, rng.uniform(-.4, .4))
    elif ty == 'sting': put(fx, sfx.whoosh(.3), t - .22, .6, -.3); put(fx, sfx.thump(1.0, 65), t, .7)
    elif ty == 'tick': put(fx, tick(1.4, .8), t, .4, .2)
    elif ty == 'swipe': put(fx, squeak(e.get('d', .3)), t, .35, .1)
    elif ty == 'marker': put(fx, squeak(e.get('d', .4)), t, .45, .15)
    elif ty == 'shutter': put(fx, shutter(), t - .02, .7)
    elif ty == 'hit': put(fx, sfx.thump(1.0, 60), t, .75)
    elif ty == 'stamp': put(fx, sfx.thump(.9, 80), t, .6); put(fx, sfx.click(.6, .8), t, .3)
    elif ty == 'draw': put(fx, squeak(e['d']) * .5, t, .3, .2)
    elif ty == 'pop': put(fx, sfx.pop(.8), t, .4, rng.uniform(-.3, .3))
    elif ty == 'ding': put(fx, sfx.ding(.6), t, .25, .2)
    elif ty == 'paper': put(fx, paper(), t, .55, -.1)
    elif ty == 'punch': put(fx, sfx.whoosh(.25), t - .2, .55); put(fx, sfx.thump(1.0, 50), t, .8)
    elif ty == 'ticks':
        for k in range(14): put(fx, tick(.9 + k * .05, .6), t + k * .05, .22, -.5 + k / 14)
    elif ty == 'riser': put(fx, riser(e['d']), t, .35)
    elif ty == 'cut' and e.get('k') in ('stock', 'stress', 'loss', 'map'): put(fx, paper(.25), t, .25, .2)

# ----------------------------------------------------------------- natural sound: the swarm (J-cut into the freeze, under the ending)
sw, ssr = sf.read(os.path.join(H, 'src', 'swarm.wav'), dtype='float32')
if sw.ndim > 1: sw = sw.mean(1)
if ssr != SR: sw = soxr.resample(sw, ssr, SR)
sw = hp(sw, 120); sw = sw / (np.sqrt(np.mean(sw ** 2)) + 1e-9) * .05
amb = buf()
def bed(src_t, at, d, g, fi=.3, fo=.4):
    x = sw[int(src_t * SR):int((src_t + d) * SR)].copy(); m = len(x); tt = np.arange(m) / SR
    x *= np.minimum(1, tt / fi) * np.minimum(1, (d - tt) / fo); put(amb, x, at, g)
bed(2.0, 0.0, 5.2, .5)          # under the hook, low
bed(10.0, 10.2, 3.0, 1.5, .25, .25)   # the freeze: the only sound with the voice (J-cut 0.3 s early)
bed(20.0, 49.6, 9.9, .6, .4, 1.5)    # silence 2, verdict, end card

# ----------------------------------------------------------------- mix
env = np.abs(vo[:, 0]); k = int(.08 * SR); env = np.convolve(env, np.ones(k) / k, 'same')
duck = 1 - .68 * np.clip(env / .03, 0, 1)
# under speech also carve 1.2–5 kHz out of the music (the consonant band), so the voice stays intelligible
vk = np.clip(env / .03, 0, 1)[:, None]; mus = mus - np.stack([bp(mus[:, c], 1200, 5000) for c in (0, 1)], 1) * .55 * vk
fxduck = 1 - .55 * np.clip(env / .03, 0, 1)
mus_r = np.sqrt(np.mean(mus ** 2)) + 1e-9; mus *= .042 / mus_r      # music about 8 dB under the voice before ducking
mix = mus * duck[:, None] + fx * fxduck[:, None] * .5 + vo + amb * fxduck[:, None]
mix = np.stack([sfx.limit(mix[:, c], .95) for c in (0, 1)], 1)
os.makedirs(os.path.join(D, 'out'), exist_ok=True); os.makedirs(os.path.join(H, 'stems'), exist_ok=True)
sf.write(os.path.join(D, 'out', 'mix.wav'), mix.astype(np.float32), SR)
for name, x in (('music', mus * duck[:, None]), ('fx', fx * fxduck[:, None] * .5), ('vo', vo), ('amb', amb * fxduck[:, None])): sf.write(os.path.join(H, 'stems', name + '.wav'), x.astype(np.float32), SR)
print('mix', DUR, 's  peak', float(np.abs(mix).max()), ' music events', len(E))

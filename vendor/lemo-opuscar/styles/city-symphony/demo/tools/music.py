"""Score (original, written in Glass-style minimalist repetition, no existing melody used): VSCO 2 CE / VCSL real samples (CC0).
Development: minimalist repetition (eighth-note arpeggios) → acceleration (triplets against eighths, staccato woodwinds) → grid section, sixteenth-note tutti → brake (arpeggios all stop, long chords)
      → restart (eighths → triplets → sixteenths) → climax flashback → hard stop (dry signal cut in one stroke, only the reverb left) → coda long chord.
Every cut lands on a beat from here (timeline.py is the single source of timing). Usage: python tools/music.py audio/music.wav"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, LIB); sys.path.insert(0, HERE)
import numpy as np, soundfile as sf
from core.audio import sampler as S
from core.audio.sfx import SR
from timeline import bar, BEAT, DUR, NOON, GRID, BRAKE, DUSK, FLASH, STOP, PAGE, CARD, SLATE

S.seed(11)
CH = {   # three arpeggio notes (low → high) + pedal bass
    'Cm': (['C4', 'Eb4', 'G4'], 'C2'), 'Ab': (['C4', 'Eb4', 'Ab4'], 'Ab1'), 'Fm': (['C4', 'F4', 'Ab4'], 'F1'),
    'G': (['B3', 'D4', 'G4'], 'G1'), 'Eb': (['Bb3', 'Eb4', 'G4'], 'Eb2'), 'Bb': (['Bb3', 'D4', 'F4'], 'Bb1'),
    'Db': (['Db4', 'F4', 'Ab4'], 'Db2'),
}
PLAN = {0: 'Cm', 1: 'Ab', 2: 'Fm', 3: 'G', 4: 'Cm', 5: 'Ab', 6: 'Eb', 7: 'Bb', 8: 'Ab', 9: 'Fm', 10: 'Db', 11: 'G',
        16: 'Cm', 17: 'Ab', 18: 'Fm', 19: 'G', 20: 'Cm'}
EV = []


def ev(t, inst, pitch, dur, vel, pan=0, gain=1.0, **kw):
    EV.append(dict(t=t, inst=inst, pitch=pitch, dur=dur, vel=vel, pan=pan, gain=gain, **kw))


def arp(n, sub, pattern, vel, pan, gain, oct_=0, inst='organ_soft', legato=1.0, b0=0, b1=4):
    tones = CH[PLAN[n]][0]; step = BEAT / sub; k = 0; t = bar(n, b0)
    while t < bar(n, b1) - 1e-6:
        p = pattern[k % len(pattern)]
        ev(t, inst, S.midi(tones[p % 3]) + 12 * (oct_ + p // 3), step * legato, vel, pan, gain)
        t += step; k += 1


def slam(n, vel=.88, g=1.0):
    tones, ped = CH[PLAN[n]]
    ev(bar(n), 'organ', S.midi(tones[0]) - 12, 1.4, vel, -.1, .55 * g)
    for p in tones: ev(bar(n), 'organ', p, 1.4, vel, .1, .42 * g)
    ev(bar(n), 'gran_cassa', 'hit', None, .75 * g, 0, .9 * g)


def pulse(n, inst='cellos_spic', per_beat=1, vel=.68, gain=.85):
    ped = CH[PLAN[n]][1]
    for k in range(4 * per_beat):
        ev(bar(n, k / per_beat), inst, S.midi(ped) + 12, .2, vel, .22, gain)


for n, c in PLAN.items():
    ped = CH[c][1]
    end = min(bar(n + 1), BRAKE if n < 12 else STOP)
    ev(bar(n), 'organ_pedal', ped, end - bar(n), .74, 0, .9, release=.2)

# ── A night → morning (bars 0–3): eighth-note arpeggios, minimalist repetition ──
slam(0)
for n in range(4):
    arp(n, 2, [0, 1, 2, 1], .7, -.25, .95)
    if n >= 2: pulse(n)
    if n == 3: arp(n, 2, [2, 1, 0, 1], .45, .4, .26, oct_=1, inst='flute_stac')
# ── B morning (bars 4–7): triplets against eighths, staccato woodwinds ──
ev(bar(4), 'organ', 'C3', .9, .75, 0, .35)
for n in range(4, 8):
    arp(n, 3, [0, 1, 2], .74, -.25, .9)
    arp(n, 2, [2, 1, 0, 1], .58, .35, .55, oct_=1, inst='clarinet_stac')
    pulse(n, vel=.7)
    if n >= 6: arp(n, 3, [0, 2, 1], .6, .45, .5, oct_=1, inst='violins_spic')
    if n == 7: arp(n, 4, [0, 1, 2, 3], .5, -.45, .35, oct_=1, inst='flute_stac')
# ── C noon (bars 8–9): slams back in; spreads out under one long take; digits locking one by one = glockenspiel ──
slam(8)
for n in (8, 9):
    arp(n, 3, [0, 1, 2], .76, -.25, .9)
    arp(n, 2, [2, 1, 0, 1], .6, .35, .55, oct_=1, inst='clarinet_stac')
    pulse(n, vel=.72)
ev(NOON, 'violins', 'Eb5', 3.9, .45, -.3, .4, attack=.4, release=.4)
ev(NOON, 'cellos', 'Ab2', 3.9, .5, .25, .5, attack=.3, release=.4)
for k in range(7):        # render.py's lock_digits: from NOON+0.3, one digit locks per sixteenth
    ev(NOON + .3 + (k + 1) * BEAT / 4, 'glockenspiel', ['C6', 'Eb6', 'F6', 'Ab6', 'G6', 'Eb6', 'C7'][k], .3, .5, .3, .45)
# ── grid (bars 10–11): sixteenth-note tutti, the cells fill up with it ──
for n in (10, 11):
    arp(n, 4, [0, 1, 2, 3, 2, 1], .82, -.25, .95)
    arp(n, 3, [0, 1, 2], .66, .3, .6, oct_=1, inst='clarinet_stac')
    arp(n, 2, [2, 1, 0, 1], .66, .45, .55, oct_=1, inst='violins_spic')
    pulse(n, per_beat=2, vel=.78, gain=.9)
    if n == 11: arp(n, 4, [3, 2, 1, 0], .62, -.45, .45, oct_=1, inst='flute_stac')
ev(bar(10), 'organ', 'Db3', 1.0, .8, 0, .4)
ev(bar(11), 'organ', 'G2', 1.0, .85, 0, .45)
ev(bar(11), 'sus_cymbal', 'cresc', None, .6, .1, .36)
# ── D brake (bars 12–15): arpeggios all stop ──
t = BRAKE
for p, g in [('Ab3', .6), ('C4', .5), ('Eb4', .45), ('G4', .4)]:
    ev(t, 'organ_soft', p, 3.0, .6, 0, g, attack=.12, release=.5)
ev(t, 'organ_pedal', 'Ab1', 3.0, .6, 0, .8, release=.4)
ev(t, 'cellos', 'Ab2', 3.0, .5, .25, .55, attack=.3, release=.5)
ev(t + .3, 'violins', 'G5', 2.6, .35, -.3, .35, attack=.8, release=.5)
ev(t + .1, 'vibraphone_bowed', 'Eb5', 2.8, .45, .35, .4)
t = bar(13, 2)            # 1899 | today: Fm9, one very short descending flute phrase
for p, g in [('F3', .55), ('Ab3', .45), ('C4', .45), ('G4', .38)]:
    ev(t, 'organ_soft', p, 4.0, .58, 0, g, attack=.15, release=.5)
ev(t, 'organ_pedal', 'F1', 4.0, .58, 0, .8, release=.4)
ev(t, 'contrabass', 'F2', 4.0, .5, .2, .45, attack=.3, release=.5)
for tt, p, d in [(t + .25, 'C5', 1.4), (t + 1.75, 'Bb4', .95), (t + 2.75, 'Ab4', 1.2)]:
    ev(tt, 'flute', p, d, .45, -.25, .5, attack=.08, release=.3)
for k in range(3):        # the three counters land
    ev(bar(13, 2) + .25 + k * BEAT / 3 + .55, 'glockenspiel', ['C6', 'Ab5', 'F5'][k], .3, .38, .3, .38)
t = bar(15, 2)            # long exposure: the pulse quietly returns, crescendo into dusk
for k in range(8):
    ev(t + k * BEAT / 4, 'organ_soft', ['C4', 'Eb4', 'G4', 'Eb4'][k % 4], BEAT / 4, .4 + .05 * k, -.25, .45 + .06 * k)
ev(bar(15), 'sus_cymbal', 'cresc', None, .6, -.1, .5)
# ── E dusk → night (bars 16–20): eighths → triplets → sixteenths → flashback ──
slam(16)
arp(16, 2, [0, 1, 2, 1], .8, -.25, .95); pulse(16, vel=.74)
arp(16, 3, [0, 1, 2], .55, .35, .5, oct_=1, inst='clarinet_stac')
arp(17, 3, [0, 1, 2], .82, -.25, .95); pulse(17, vel=.76)
arp(17, 2, [2, 1, 0, 1], .62, .35, .55, oct_=1, inst='clarinet_stac')
arp(17, 3, [0, 2, 1], .62, .45, .5, oct_=1, inst='violins_spic')
for n in (18, 19, 20):
    arp(n, 4, [0, 1, 2, 3, 2, 1], .86, -.25, 1.0)
    arp(n, 3, [0, 1, 2], .7, .3, .62, oct_=1, inst='clarinet_stac')
    arp(n, 4 if n >= 19 else 3, [3, 2, 1, 0], .7, .45, .6, oct_=1, inst='violins_spic')
    pulse(n, per_beat=2, vel=.82, gain=.95)
    if n >= 19: arp(n, 4, [0, 1, 2, 3], .6, -.45, .45, oct_=1, inst='flute_stac')
    ev(bar(n), 'gran_cassa', 'hit', None, .6, 0, .7)
ev(bar(18) + .75, 'glockenspiel', 'G6', .4, .45, .3, .4)        # the 220,000 count lands
ev(bar(20), 'organ', 'C3', 2.0, .9, 0, .5)
for p in ['G3', 'C4', 'Eb4', 'G4']: ev(bar(20), 'organ', p, 2.0, .9, 0, .34)
ev(bar(19, 2), 'sus_cymbal', 'cresc', None, .75, .1, .6)
for p, q in (('G3', 'D4'), ):
    ev(bar(19), 'horn', p, 2.0, .62, -.2, .42, attack=.25, release=.2); ev(bar(19), 'horn', q, 2.0, .6, .2, .36, attack=.25, release=.2)
ev(bar(20), 'horn', 'C4', 2.0, .7, -.2, .48, attack=.15, release=.1); ev(bar(20), 'horn', 'G4', 2.0, .68, .2, .4, attack=.15, release=.1)
ev(bar(20), 'gran_cassa', 'roll', None, .62, 0, .55)
# ── F coda ──
ev(PAGE - .05, 'organ_pedal', 'C2', 1.5, .5, 0, .6, attack=.35, release=.6)
for p, g in [('C3', .4), ('Ab3', .4), ('Bb3', .3), ('Eb4', .35), ('C5', .22)]:
    ev(CARD, 'organ_soft', p, SLATE - CARD - .2, .5, 0, g, attack=.6, release=.9)
ev(CARD, 'organ_pedal', 'Ab1', SLATE - CARD - .2, .45, 0, .55, attack=.6, release=.9)
ev(CARD + .5, 'violins', 'Eb5', SLATE - CARD - .8, .32, -.3, .3, attack=1.0, release=.8)
# end slate: the opening arpeggio slowly returns in quarter notes (the city keeps turning), stopping on an unresolved Fm9/Ab
for p, g in [('Ab2', .38), ('C4', .32), ('Eb4', .3), ('G4', .26), ('Bb4', .2)]:
    ev(SLATE, 'organ_soft', p, DUR - SLATE - .4, .48, 0, g, attack=.7, release=1.2)
for k in range(int((DUR - SLATE - 1.5) / BEAT)):
    ev(SLATE + .5 + k * BEAT, 'organ_soft', ['C5', 'Eb5', 'G5', 'Eb5'][k % 4], BEAT, .38, -.3, .28 * (1 - k / 22))
ev(SLATE + .4, 'flute', 'G5', 4.0, .32, .3, .3, attack=.8, release=1.0)

# dynamic arc: leave headroom at the start, sink in the brake section, loudest at dusk
for e in EV:
    if e['t'] < bar(4) and e['inst'] not in ('organ', 'gran_cassa'): e['gain'] *= (.7 if e['t'] >= bar(3) else .82)
    elif bar(4) <= e['t'] < bar(8): e['gain'] *= 1.12
    elif bar(19) <= e['t'] < STOP: e['gain'] *= 1.12
    elif BRAKE - .01 <= e['t'] < DUSK - .01 and e['inst'] != 'sus_cymbal': e['gain'] *= .62
N = int(DUR * SR)


def cut_at(x, t):
    c = int(t * SR); f = int(.015 * SR); y = x.copy()
    y[c:c + f] *= np.linspace(1, 0, f)[:, None]; y[c + f:] = 0
    return y


# two hard cuts: grid → brake (24.0), flashback → black (42.0). The dry signal is cut, the reverb tail stays
A = S.render([e for e in EV if e['t'] < BRAKE - .01], dur=DUR + 1.5, master=False)
B = S.render([e for e in EV if BRAKE - .01 <= e['t'] < STOP - .01], dur=DUR + 1.5, master=False)
C = S.render([e for e in EV if e['t'] >= STOP - .01], dur=DUR + 1.5, master=False)
A = cut_at(A, BRAKE); B = cut_at(B, STOP)
wet = S.room(A + B, size=.7, mix=.28) + S.room(C, size=.78, mix=.36)
mix = wet[:N]
fo = int(1.2 * SR); mix[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 2
mix /= max(1e-6, np.abs(mix).max()) / .89
out = sys.argv[1] if len(sys.argv) > 1 else 'audio/music.wav'
sf.write(out, mix.astype(np.float32), SR)
print(out, len(EV), 'events', f'{len(mix) / SR:.2f}s')
print(S.credits(sorted({e['inst'] for e in EV})))

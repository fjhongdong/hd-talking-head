// Timeline: 120 BPM, 1 beat = 0.5 s, 1 bar = 2 s. Every cut, light sweep and pulse is aligned to the beat (music first)
export const BPM = 120, BEAT = .5, BAR = 2;
export const DUR = 32;
export const b = n => n * BAR;   // start of bar n

export const T = {
  sweep1: [0.5, 1.7], sweep2: [2.0, 3.2],        // two light sweeps over black
  title: [1.0, 3.9],
  lidOpen: [4.5, 7.6], lidClick: 8.0,            // lid swings slowly open, magnetic snap home at 8.0
  lift: [8.0, 9.4],                              // right earbud lifts off its magnet
  explode: [12.0, 15.2], hold: 15.5, snap: 16.0, // exploded view → held breath → snaps back together at 16.0 (the drop)
  liftL: [20.0, 21.2],
  reveal: 24.0, settle: [27.0, 27.8],            // closing light sweep + both earbuds drop back into their cradles
  name: [24.5, 27.7], end: 28.0,
};

// Shot list (every cut is on a bar line)
export const SHOTS = [
  [0, 4, 'dark'], [4, 8, 'open'], [8, 10, 'macroA'], [10, 12, 'macroB'], [12, 17, 'explode'],
  [17, 18, 'front'], [18, 20, 'channels'], [20, 22, 'pair'], [22, 24, 'caustics'], [24, 28, 'reveal'], [28, 32, 'end'],
];
export const shotAt = t => SHOTS.find(s => t >= s[0] && t < s[1]) || SHOTS[SHOTS.length - 1];

// Drum hits for the sound-visualisation section (808 kick): variations on beats 1, 2&, 3, 4 of each bar; outside the section only a few big accents
const KPAT = [0, .75, 1.0, 1.5];
export const KICKS = [];
for (let bar = 8; bar < 12; bar++) for (const o of KPAT) KICKS.push({ t: b(bar) + o, big: o === 0 && (bar === 8) });
KICKS.push({ t: 24.0, big: true });
// Light sweeps in the macro section: one per beat (locked to the kick)
export const MACRO_SWEEPS = [8.0, 9.0, 10.0, 11.0];

// Narration (am_michael)
export const VO = [
  { id: 'v1', t: 8.55, text: 'Nothing to hide.' },
  { id: 'v2', t: 12.45, text: 'Every part, in plain sight.' },
  { id: 'v3', t: 24.5, text: 'Meet Aura.' },
  { id: 'v4', t: 25.8, text: 'Hear the light.' },
];

// Foley events (materials: glass, metal, magnets); mix.py reads them from events.json
export const SFX = [
  { t: 0.45, type: 'sweep', d: 1.3, pan: [-.8, .8], v: .5 },
  { t: 1.95, type: 'sweep', d: 1.3, pan: [.8, -.8], v: .55 },
  { t: 4.5, type: 'slide', d: 3.1, v: .5 },                 // slow friction of the glass lid against its hinge
  { t: 7.55, type: 'tock', v: .5 },                         // lid reaches its stop
  { t: 8.0, type: 'click', v: .9, pan: .3 },                // magnet releases, earbud lifts
  { t: 8.02, type: 'lift', d: 1.2, v: .35, pan: .3 },
  ...[8.0, 9.0, 10.0, 11.0].map(t => ({ t: t - .02, type: 'sweep', d: .5, pan: [-.6, .6], v: .22 })),
  ...[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => ({ t: 12.02 + i * .07, type: 'puff', v: .28 + (i % 3) * .06, pan: -.6 + i * .13 })),
  { t: 12.0, type: 'slowwhoosh', d: 2.6, v: .5 },
  { t: 15.55, type: 'revwhoosh', d: .45, v: .8 },           // in full silence the parts get pulled back
  { t: 16.0, type: 'snap', v: 1.0 },                        // snap together: cluster of magnetic clicks + glass ting
  { t: 20.0, type: 'lift', d: 1.1, v: .35, pan: -.6 },      // left earbud flies in
  { t: 23.95, type: 'sweep', d: 1.35, pan: [-.8, .8], v: .5 },
  { t: 27.72, type: 'click', v: .75, pan: -.35 },           // drops back into its cradle
  { t: 27.84, type: 'click', v: .75, pan: .35 },
];

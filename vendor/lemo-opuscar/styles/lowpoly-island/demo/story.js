// Timeline: 96 BPM; bars of the groove are counted from when the first tile rises (6.25s). Every cut and growth event aligns to this grid.
export const DUR = 53.0;
export const BPM = 96, BEAT = 60 / BPM, BAR = BEAT * 4;   // 0.625 / 2.5
export const G0 = 6.25;                                    // groove bar 0
export const bar = n => G0 + n * BAR;
export const beat = n => G0 + n * BEAT;

export const T = {
  bell1: 0.25, bell2: 2.9,
  title: [0.6, 3.6],
  first: bar(0),            // 6.25 first tile
  tiles: bar(1),            // 8.75
  trees: bar(3),            // 13.75
  houses: bar(4),           // 16.25
  details: bar(5),          // 18.75
  day: bar(6),              // 21.25 cut: daytime time-lapse
  dock: bar(7),             // 23.75 cut: the dock, the boat heads out to sea
  dusk: bar(8),             // 26.25 cut: dusk wide shot, windows light up one by one
  night0: bar(9),           // 28.75 the sky fades into night
  night: bar(10),           // 31.25 cut: night, negative space
  rise: bar(11),            // 33.75 the lighthouse's four rings
  ignite: bar(12),          // 36.25 ignition (the strongest beat of the film)
  found: bar(13) + 0.625,   // 39.375 the beam finds the boat (beat 5 = the rest in the melody)
  home: bar(14),            // 41.25 return to harbour + pull-back begins
  docked: bar(14) + 1.25,   // 42.5 docked
  far: bar(15),             // 43.75
  bellFar: 47.5,            // distant buoy bell (same note as the opening)
  end: bar(17),             // 48.75 end card
};

export const VO = [
  { id: 'v1', t: 3.7, text: 'Once, the ocean knew only one note.' },
  { id: 'v2', t: 7.0, text: 'Then, the ground began to sing.' },
  { id: 'v3', t: 26.5, text: 'By evening, every house knew its part.' },
  { id: 'v4', t: 31.25, text: 'But one note was still missing.' },
  { id: 'v5', t: 44.0, text: 'Far away, another island hears its first note.' },
];

// harmony (per groove bar), used to pick pitches for events; the score script reads the same data
export const CHORDS = ['D', 'Bm', 'G', 'A', 'D', 'Bm', 'G', 'D', 'D', 'Bm', 'D', 'A', 'D', 'Bm', 'G', 'D', 'D', 'D'];
const CT = { D: [62, 66, 69], Bm: [59, 62, 66], G: [55, 59, 62], A: [57, 61, 64] };
export const chordAt = t => CHORDS[Math.max(0, Math.min(CHORDS.length - 1, Math.floor((t - G0) / BAR)))];
// take the k-th note of the chord at time t that falls within [lo,hi] (k is a contour value in 0..1)
export function noteAt(t, k, lo = 60, hi = 84) {
  const pcs = CT[chordAt(t)], ns = [];
  for (let m = lo; m <= hi; m++) if (pcs.some(p => (m - p) % 12 === 0)) ns.push(m);
  return ns[Math.max(0, Math.min(ns.length - 1, Math.round(k * (ns.length - 1))))];
}

// sky keyframes: [t, zenith, horizon / far-sea fog, deep sea, shallow sea, sun colour, sun intensity, ambient sky light, ambient ground light, ambient intensity, sun elevation°, sun azimuth°, night amount]
export const SKY = [
  [0.0, '#9fb6cf', '#f3d2c4', '#4f8ea3', '#8fc9c4', '#ffd9bf', 1.3, '#dfe6f2', '#b89a8a', 1.05, 12, 200, 0],
  [6.0, '#a9c4dc', '#f6dccd', '#4f93a8', '#93d0c8', '#ffe2c8', 1.7, '#e3ecf6', '#bfa590', 1.1, 22, 190, 0],
  [14.0, '#8fcbe6', '#e9f3f0', '#3aa3b8', '#86e0d2', '#fff4e2', 2.5, '#eef6fb', '#c2b59a', 1.15, 48, 150, 0],
  [21.25, '#88c8e8', '#eaf5f2', '#38a5bc', '#86e2d4', '#fff6e8', 2.7, '#eef6fb', '#c6b89c', 1.15, 52, 175, 0],
  [23.75, '#8cc4e4', '#f0f2e6', '#3aa0ba', '#8aded0', '#fff0d8', 2.6, '#eff3f4', '#c6b89c', 1.12, 40, 95, 0],
  [26.0, '#9ab8d8', '#ffd9b0', '#4f8fb0', '#9ed6c8', '#ffc98e', 2.2, '#f3e2d4', '#c89a80', 1.0, 22, 120, 0],
  [28.0, '#6f6fa8', '#ffa888', '#5a6a9e', '#b08aa6', '#ff9a68', 1.5, '#d8b8c8', '#a07a80', .8, 8, 105, .15],
  [30.0, '#2a2e5e', '#8a6a9c', '#2e3160', '#474a80', '#ff8a70', .35, '#7a80b8', '#5a5070', .55, 1, 100, .6],
  [31.25, '#12163a', '#4a4478', '#23264a', '#363a66', '#a9b0e8', .9, '#5c5ea8', '#2a2640', .55, 30, 300, 1],
  [53.0, '#11153a', '#4a4478', '#22254a', '#353965', '#a9b0e8', .9, '#5c5ea8', '#2a2640', .55, 30, 300, 1],
];

// camera segments: [start, end, name]
export const SHOTS = [
  [0, beat(7), 'grow'],        // opening empty sea → first tile → tiles spread out (turntable, slow pull-back)
  [beat(7), bar(2) + BAR / 2, 'rock'],   // 10.625 cut to close-up: the central rock bursts out of the water (splash)
  [bar(2) + BAR / 2, T.trees, 'grow2'],   // 12.5 back to the whole island (turntable continues)
  [T.trees, T.houses, 'trees'],           // 13.75 medium shot: trees "pop" up
  [T.houses, T.details, 'houses'],        // 16.25 close-up: storeys settle one by one with a springy bounce
  [T.details, T.day, 'details'],          // 18.75 close-up: windmill, dock planks, the boat drops into the water
  [T.day, T.dock, 'square'],
  [T.dock, T.dusk, 'dock'],
  [T.dusk, T.night, 'dusk'],
  [T.night, T.rise, 'lost'],
  [T.rise, T.ignite, 'tower'],
  [T.ignite, DUR, 'beam'],     // ignition → pull-back → end card
];
export const shotAt = t => SHOTS.find(s => t >= s[0] && t < s[1]) || SHOTS[SHOTS.length - 1];

export const CREDITS = [
  'Music, sound & 3D: original, generated in code · Voice: Kokoro TTS (af_sky)',
  'Fonts: Josefin Sans, Quicksand (SIL OFL)',
];

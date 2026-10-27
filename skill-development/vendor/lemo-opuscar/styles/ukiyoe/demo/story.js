// Timeline (single source of truth): camera, printing, title slips, narration and music cues are all derived from here
export const DUR = 44.0;
export const q8 = t => Math.floor(t * 8) / 8;     // characters and nature: 8 fps
export const q12 = t => Math.floor(t * 12) / 12;  // rain, wave claws: 12 fps

// Positions of the five pictures on the handscroll (right to left: the first picture is rightmost)
export const GAP = 260, SW = 1920 + GAP;
export const SLOT = i => (4 - i) * SW;

export const T = {
  // Opening print: key line → blue → green → red
  print1: [0.35, 1.05, 1.70, 2.30],
  title: [2.9, 5.2],
  // Each act (settled time, pan interval)
  v1: [0, 10.5], pan12: [10.5, 11.5],
  v2: [11.5, 16.4], pan23: [16.4, 17.3],
  v3: [17.3, 22.3], pan34: [22.3, 22.9],
  v4: [22.9, 30.4],
  // Great wave in four beats: rise → hang (mie, the held pose) → fall toward the camera → foam fills the frame and becomes paper
  waveRise: [25.4, 27.3], hang: [27.3, 28.5], fall: [28.5, 29.7], crash: [29.7, 30.4],
  ma: [30.4, 32.2],
  print5: [32.2, 32.7, 33.2, 33.7],
  v5: [32.2, 44],
  hatOff: [37.1, 37.8],
  pull: [38.9, 40.9],
  endcard: 40.3,
  // Title slips and seals (the full stop of each act)
  cart: { v1: [9.6, 10.1], v2: [15.5, 16.0], v3: [21.5, 21.95], v5: [37.9, 38.4] },
};
export const REVEAL_DUR = 0.34;   // time for one block to take the ink

// Narration: line id → start time
export const VO = { L1: 6.0, L2: 12.3, L3: 18.0, L4: 23.5, L5: 34.4 };

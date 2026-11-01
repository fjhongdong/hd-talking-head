// Timeline: the single source of truth. Camera keyframes, dialogue, PA, light flickers, focus, tape breaks and subtitles are all read from here
// Coordinates: metres; x east, z south (-z = north, the corridor direction); yaw 0 = facing north, +π/2 = facing west (left turn), −π/2 = facing east
import { track, monotone } from '/core/lib.js';

const PI = Math.PI;
// Time compression (the whole film squeezed under 60 s): all times below are written in "original time", then mapped to film time through W().
// Only the walking stretches are compressed: start after the pan −0.3 s, zoom pull-back −0.3 s, walk to the exit door and into the room −0.7 s; the end card and the hold before REC goes off are untouched
const WARP = [[0, 0], [7.0, 7.0], [7.9, 7.6], [39.6, 39.3], [40.2, 39.6], [49.5, 48.9], [54.3, 53.0]];
export function W(t) {
  for (let i = 0; i < WARP.length - 1; i++) { const [a, A] = WARP[i], [b, B] = WARP[i + 1]; if (t <= b) return A + (t - a) * (B - A) / (b - a); }
  const [a, A] = WARP[WARP.length - 1]; return A + (t - a);
}
const K = arr => arr.map(([t, v]) => [W(t), v]);
export const DUR = W(61.0);

// —— Key moments ——
const T0 = {
  rollIn: .55,          // tape picture rolls in
  afLock: 1.55,         // first successful focus lock
  title: [1.1, 4.6],    // camcorder character-generator title
  chime0: 1.9, p0: 2.7,
  w1: 5.55,
  pan: [6.0, 7.3],
  chime1: 7.9, p1: 8.7,
  lookDown1: [11.3, 13.4],
  chime2: 13.0, p2: 13.8,
  notice2: [16.2, 21.2],   // the same notice a second time (in a different place), read up to rule 5
  chime3: 21.6, p3: 22.4,
  flick: [27.45, 27.95, 28.45],   // three light flickers
  lookDown2: [28.55, 31.1],
  rise: [31.1, 32.3],
  zoom: [32.2, 33.4],
  figOn: [32.2, 33.95],   // time "the Thing" is in frame (out of focus most of the time)
  afFig: [33.15, 33.65],  // focus briefly sharp, it is seen
  w2: 34.05,
  afEmpty: 35.15,         // second focus lock: it's already gone
  tear: [36.35, 37.0],    // tape tracking tear → timecode +3 hours
  w3: 37.7,
  unzoom: [39.6, 40.4],
  chime4: 40.2, p4: 41.0,
  turn: [42.7, 44.5],
  hush: [47.35, 48.35],   // all sound gone for 1 second: the space holds its breath
  w4: 48.55,
  door: [51.0, 52.3],
  afFinal: 54.1,
  p6: 54.35,
  recOff: 57.7,
  endCard: [58.1, 61.0],
};
export const T = Object.fromEntries(Object.entries(T0).map(([k, v]) => [k, Array.isArray(v) ? v.map(W) : W(v)]));

// —— Lines (id matches lines.json / voices); t = start second ——
export const LINES = [
  { id: 'p0', t: T.p0, who: 'PA' }, { id: 'w1', t: T.w1, who: 'ME' },
  { id: 'p1', t: T.p1, who: 'PA' }, { id: 'p2', t: T.p2, who: 'PA' },
  { id: 'p3', t: T.p3, who: 'PA' }, { id: 'w2', t: T.w2, who: 'ME' },
  { id: 'w3', t: T.w3, who: 'ME' }, { id: 'p4', t: T.p4, who: 'PA' },
  { id: 'w4', t: T.w4, who: 'ME' }, { id: 'p6', t: T.p6, who: 'PA' },
];
export const CHIMES = [T.chime0, T.chime1, T.chime2, T.chime3, T.chime4];

// —— Camera (position / heading / pitch / field of view / focus) ——
const W0 = [0.05, 0.0];
export const POS = track(K([
  [0, W0], [6.6, W0], [13.0, [0.1, -8.4]], [14.6, [-0.25, -11.0]], [16.2, [-0.85, -12.5]],
  [17.2, [-0.9, -12.5]], [19.0, [-1.06, -12.62]], [21.2, [-1.07, -12.62]], [22.2, [-0.2, -13.4]],
  [27.1, [0.1, -19.2]], [40.9, [0.1, -19.2]], [43.0, [0.25, -21.9]], [44.6, [1.4, -22.2]],
  [47.3, [3.0, -22.2]], [49.5, [3.0, -22.2]], [52.5, [7.0, -22.2]], [53.6, [9.6, -22.2]], [54.3, [10.45, -22.2]], [61.0, [10.45, -22.2]],
]));
export const YAW = monotone(K([
  [0, PI / 2], [6.0, PI / 2], [7.3, 0.02], [13.6, 0.0], [14.6, 0.35], [16.2, PI / 2], [21.2, PI / 2], [22.3, 0.05],
  [27.1, 0.0], [42.7, 0.0], [44.5, -PI / 2], [61.0, -PI / 2],
]));
export const PITCH = monotone(K([
  [0, -0.05], [6.0, -0.05], [7.3, -0.06], [11.3, -0.08], [12.0, -1.22], [13.0, -1.18], [13.5, -0.12],
  [16.2, -0.12], [17.2, -0.1], [19.0, -0.12], [21.2, -0.13], [22.2, -0.06],
  [28.55, -0.06], [28.85, -1.28], [31.1, -1.2], [32.3, -0.015], [40.9, -0.02],
  [44.5, 0.04], [47.3, 0.06], [49.5, 0.05], [52.5, 0.0], [53.6, -0.08], [54.3, -0.12], [61.0, -0.12],
]));
// Field of view (horizontal, degrees): zoom in to look at the end of the corridor
// Camera height offset (metres): crouch a little while reading the notices so the lens is parallel to the paper (otherwise the keystone of a downward angle skews the text)
export const CAMH = monotone(K([[0, 0], [16.4, 0], [18.6, -0.16], [21.2, -0.16], [22.2, 0], [61.0, 0]]));
export const FOV = monotone(K([[0, 52], [32.2, 52], [33.4, 27], [39.6, 27], [40.4, 52], [61.0, 52]]));
// Autofocus: focus distance (metres); AF hunting = racking back and forth
export const FOCUS = monotone(K([
  [0, 0.4], [0.8, 0.5], [1.2, 3.5], [1.55, 1.7], [6.5, 1.7], [7.3, 6], [16.2, 3], [16.8, 0.35], [17.2, 0.7], [17.5, 0.62],
  [19.0, 0.46], [21.2, 0.46], [22.2, 5], [28.6, 5], [29.0, 1.5], [32.2, 1.8],
  [32.8, 2.5], [33.02, 3.5], [33.15, 33.2], [33.65, 32.8], [33.95, 70], [34.35, 4], [34.8, 12], [35.15, 33.3], [39.6, 33.3], [40.4, 6],
  [53.4, 3], [53.8, 0.35], [54.1, 0.8], [61.0, 0.8],
]));
// Aperture (depth-of-field strength, pixels/dioptre): depth of field gets shallower at the long end of the zoom
export const APER = monotone(K([[0, 3.0], [32.2, 3.0], [33.4, 14], [39.6, 14], [40.4, 3.0], [61.0, 3.0]]));
// Hand shake / fear level (0 calm … 1 trembling); hold = holding breath, all handheld shake frozen
export const FEAR = monotone(K([[0, 0.15], [20, 0.2], [27.4, 0.3], [28.6, 0.85], [31.5, 0.7], [34.0, 0.9], [37.0, 0.55], [44.5, 0.6], [47.3, 0.8], [49.5, 0.8], [55, 0.6], [61.0, 0.6]]));
export const HOLD = t => (t > T.hush[0] - 0.1 && t < T.hush[1] + 0.25) ? 0 : 1;

// —— OSD timecode (part of the story) ——
export function clock(t) {
  if (t < T.tear[0] + 0.3) return t < W(19.5) ? 'PM 11:58' : 'PM 11:59';
  return t < W(50.0) ? 'AM  2:59' : 'AM  3:00';
}
export const battery = t => t < T.tear[0] + 0.3 ? 3 : 1;   // battery bars (after the tear only one is left, blinking)

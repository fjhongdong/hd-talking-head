// Camera keyframes: t seconds, (x,y) composition centre (paper units), z zoom (1 = whole face), r rotation (degrees), f follow weight (0 = pure composition, 1 = pure pen following)
export const CAM = [
  { t: 0.0, x: -272, y: -18, z: 4.5, r: 0, f: 0 },
  { t: 1.0, x: -274, y: -18, z: 4.3, r: 0, f: .12 },          // birth: the small hand centred in frame
  { t: 4.4, x: -280, y: -16, z: 4.1, r: 0, f: .12 },
  { t: 5.2, x: -262, y: -120, z: 3.0, r: -3, f: .8 },          // the kite string climbs along the edge of the face
  { t: 5.9, x: -120, y: -420, z: 2.5, r: -2, f: .8 },          // bald crown
  { t: 6.6, x: 40, y: -600, z: 2.5, r: 3, f: .25 },            // hair, kite
  { t: 8.2, x: 70, y: -590, z: 2.6, r: 2, f: .25 },            // tail, reeling in
  { t: 9.0, x: 60, y: -440, z: 2.4, r: 0, f: .7 },
  { t: 9.7, x: 180, y: -200, z: 2.3, r: 0, f: .6 },            // other half of the crown → right temple
  { t: 10.4, x: 60, y: -70, z: 2.05, r: 0, f: .2 },            // bicycle: rides past from right to left
  { t: 13.4, x: -70, y: -70, z: 2.05, r: 0, f: .2 },
  { t: 14.3, x: -110, y: 90, z: 2.8, r: 0, f: .65 },           // down the left lens frame and nasolabial fold to the mouth corner
  { t: 15.0, x: -20, y: 206, z: 3.7, r: 0, f: .15 },           // first love: mouth centred
  { t: 18.9, x: 10, y: 206, z: 3.7, r: 0, f: .15 },
  { t: 19.8, x: -60, y: 130, z: 3.4, r: 0, f: .5 },            // back up the nasolabial fold along the same path
  { t: 20.6, x: 0, y: 62, z: 4.1, r: 0, f: .2 },               // house
  { t: 22.4, x: 10, y: 60, z: 4.1, r: 0, f: .2 },
  { t: 23.2, x: 128, y: 6, z: 4.6, r: 0, f: .15 },             // loss: the eye
  { t: 26.8, x: 140, y: 10, z: 5.4, r: 0, f: .1 },             // very slow push-in while the pen is stopped
  { t: 27.6, x: 250, y: -30, z: 4.3, r: 0, f: .35 },           // child: mirror of the birth composition
  { t: 30.2, x: 280, y: -16, z: 4.1, r: 0, f: .12 },
  { t: 31.2, x: 250, y: 100, z: 3.1, r: 0, f: .75 },           // old age: down along the right side of the face
  { t: 33.3, x: 110, y: 330, z: 2.7, r: 0, f: .6 },
  { t: 38.5, x: 0, y: -190, z: 0.98, r: 0, f: 0 },             // one continuous pull-back: the whole face
  { t: 39.7, x: 0, y: -186, z: 0.99, r: 0, f: 0 },             // hold the gaze
  { t: 40.9, x: -170, y: 40, z: 1.85, r: 0, f: 0 },            // push in to the closed left eye: hand-over
  { t: 41.9, x: -180, y: 50, z: 1.85, r: 0, f: .15 },
  { t: 44.2, x: -110, y: -170, z: 0.94, r: 0, f: 0 },          // pull back following the new line: the child's kite on the left, end card on the right
  { t: 47.5, x: -118, y: -170, z: 0.94, r: 0, f: 0 },
];

// For testing content swapping: wireframe model of KITE M2, a fictional folding camera drone → kite.json
// Usage: node gen_kite.mjs > kite.json    Coordinates: metres; x forward (nose), y up, z left.
import { Model } from './mkmodel.mjs';
const M = new Model('KITE M2');
const BY = 0.085;                     // body centre height

// ---------- Body ----------
M.part('body', { anchor: [0, BY + 0.03, 0] });
M.piece('hull');
M.tube([-0.11, BY, 0], [0.1, BY, 0], 0.042, { rings: 9, seg: 14, longs: 7 });
M.disc([0.1, BY, 0], [1, 0, 0], 0.042, { rings: [0.042, 0.03, 0.015], seg: 14 });
M.disc([-0.11, BY, 0], [-1, 0, 0], 0.042, { rings: [0.042, 0.028], seg: 14 });
M.box([-0.005, BY + 0.045, 0], [0.15, 0.012, 0.06]);            // top cover
M.tube([-0.02, BY + 0.052, 0], [0.04, BY + 0.052, 0], 0.006, { rings: 2, seg: 8, longs: 3 });   // top indicator light bar
// legs (under the arms)
// landing gear: comes out of the belly (on the body shell wall), with foot pads where it touches the ground
for (const [x, z] of [[0.07, 0.024], [0.07, -0.024], [-0.08, 0.024], [-0.08, -0.024]]) {
  M.box([x, BY - 0.036, z], [0.016, 0.01, 0.012]);                                   // belly mount (attached to the body shell wall)
  M.tube([x, BY - 0.036, z], [x * 1.25, 0.004, z * 2.9], 0.005, { rings: 3, seg: 6, longs: 2 });
  M.box([x * 1.25, 0.004, z * 2.9], [0.03, 0.008, 0.012]);                           // foot pad
}

// ---------- Arms + motors + propellers ----------
M.part('arms', { anchor: [-0.15, BY + 0.03, 0.155], center: [-0.15, BY + 0.05, 0.155], tagDir: -1 });
M.piece('arm-beams');
const ends = [[0.15, 0.155], [0.15, -0.155], [-0.15, 0.155], [-0.15, -0.155]];
for (const [x, z] of ends) {
  const hx = Math.sign(x) * 0.05, hz = Math.sign(z) * 0.035;
  M.tube([hx, BY - 0.006, hz], [hx, BY + 0.028, hz], 0.012, { rings: 4, seg: 12, longs: 6 });   // folding hinge: vertical pin barrel (the arm folds around it back against the body)
  M.box([hx - Math.sign(x) * 0.012, BY + 0.01, hz - Math.sign(z) * 0.004], [0.022, 0.03, 0.014]);  // hinge mount (connects to the body)
  M.circle([hx, BY + 0.03, hz], [0, 1, 0], 0.005, 8);                                              // pin cap
  M.tube([hx, BY + 0.01, hz], [x, BY + 0.02, z], 0.011, { rings: 6, seg: 8, longs: 4 });
  M.tube([x, BY + 0.005, z], [x, BY + 0.03, z], 0.019, { rings: 3, seg: 12, longs: 6 });       // motor housing
}
M.piece('props', { explode: [0, 0.07, 0] });
for (const [x, z] of ends) {
  const c = [x, BY + 0.04, z];
  M.circle(c, [0, 1, 0], 0.075, 40);                                             // propeller disc
  M.tube([x, BY + 0.032, z], [x, BY + 0.042, z], 0.008, { rings: 2, seg: 8, longs: 4 });
  for (const a of [0.3, 0.3 + Math.PI]) {                                         // two blades
    const p = [x + Math.cos(a) * 0.07, BY + 0.04, z + Math.sin(a) * 0.07];
    M.polyTube([[x, BY + 0.04, z], [x + Math.cos(a + 0.12) * 0.035, BY + 0.043, z + Math.sin(a + 0.12) * 0.035], p], 0.005, { seg: 6, longs: 2, ringsPer: 2 });
  }
}
M.piece('motor-core', { explode: [0, 0.035, 0], internal: true, hot: true });
for (const [x, z] of ends) M.stator([x, BY + 0.018, z], 0.016, 0.006, 0.01, 9);

// ---------- Battery (slots into the tail of the body): the shell slides out backwards along the body axis, the cells stay in place and glow ----------
M.part('battery', { anchor: [-0.075, BY + 0.01, 0.045], center: [-0.12, BY, 0.0], tagDir: -1 });
M.piece('battery-pack', { explode: [-0.14, 0, 0] });
M.box([-0.07, BY + 0.005, 0], [0.09, 0.05, 0.07]);
M.box([-0.118, BY + 0.005, 0], [0.006, 0.03, 0.05]);                               // pull tab
M.piece('battery-cells', { internal: true, hot: true });
for (const z of [-0.018, 0.018]) M.tube([-0.105, BY + 0.005, z], [-0.035, BY + 0.005, z], 0.014, { rings: 3, seg: 10, longs: 4 });

// ---------- Gimbal camera ----------
M.part('camera', { anchor: [0.155, BY - 0.035, 0.03], center: [0.16, BY - 0.035, 0.0], tagDir: 1 });
M.piece('gimbal-yoke');
M.tube([0.1, BY - 0.03, 0], [0.13, BY - 0.035, 0], 0.008, { rings: 3, seg: 8, longs: 3 });
M.polyTube([[0.13, BY - 0.035, -0.028], [0.13, BY - 0.035, 0.028]], 0.005, { seg: 6, longs: 2, ringsPer: 3 });
for (const z of [-0.028, 0.028]) M.tube([0.13, BY - 0.035, z], [0.15, BY - 0.045, z], 0.004, { rings: 2, seg: 6, longs: 2 });
M.piece('camera-head', { explode: [0.07, -0.02, 0] });
M.box([0.158, BY - 0.045, 0], [0.036, 0.034, 0.044]);
M.tube([0.176, BY - 0.045, 0], [0.19, BY - 0.045, 0], 0.013, { rings: 3, seg: 14, longs: 6 });
M.disc([0.19, BY - 0.045, 0], [1, 0, 0], 0.013, { rings: [0.013, 0.008, 0.004], seg: 14 });
M.piece('camera-sensor', { explode: [0.035, -0.01, 0], internal: true, hot: true });
M.box([0.158, BY - 0.045, 0], [0.004, 0.02, 0.026]);

// ---------- Obstacle sensors: front and rear stereo pairs + bottom ----------
M.part('sensors', { anchor: [0.1, BY + 0.01, 0.02], center: [0.06, BY, 0], tagDir: -1 });
M.piece('sensor-front', { explode: [0.06, 0.015, 0] });
for (const z of [-0.022, 0.022]) M.disc([0.104, BY + 0.012, z], [1, 0, 0], 0.009, { rings: [0.009, 0.005], seg: 12 });
M.box([0.101, BY + 0.012, 0], [0.004, 0.02, 0.07]);
M.piece('sensor-rear', { explode: [-0.06, 0.015, 0] });
for (const z of [-0.022, 0.022]) M.disc([-0.114, BY + 0.018, z], [-1, 0, 0], 0.008, { rings: [0.008, 0.004], seg: 12 });
M.piece('sensor-bottom', { explode: [0, -0.04, 0] });
for (const x of [-0.02, 0.02]) M.disc([x, BY - 0.043, 0], [0, -1, 0], 0.008, { rings: [0.008, 0.004], seg: 12 });

process.stdout.write(JSON.stringify(M.toJSON()));

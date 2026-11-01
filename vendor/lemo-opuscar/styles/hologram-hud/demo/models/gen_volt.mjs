// Generates the wireframe model of the VOLT CE-01 city e-bike (vertices + edges + quad faces), writes volt.json
// Usage: node gen_volt.mjs > volt.json
// Coordinates: metres; x forward (front of bike), y up, z towards the bike's left side. Ground at y = 0.
import { Model } from './mkmodel.mjs';

const M = new Model('VOLT CE-01');
const R = 0.35;                       // wheel radius (including tyre)
const RA = [-0.56, R, 0], FA = [0.56, R, 0];   // rear axle / front axle
const BB = [-0.04, 0.29, 0];          // bottom bracket
const ST = [-0.24, 0.84, 0];          // top of seat tube
const HB = [0.40, 0.66, 0], HT = [0.35, 0.86, 0];   // head tube bottom / top
const SC = [-0.21, 0.76, 0];          // seat-stay junction

// ---------- Frame ----------
M.part('frame', { anchor: [0.1, 0.7, 0] });
M.piece('frame-main');
M.tube(BB, ST, 0.019, { rings: 9, seg: 10, longs: 4 });                      // seat tube
M.tube([-0.22, 0.79, 0], [0.37, 0.80, 0], 0.017, { rings: 10, seg: 10, longs: 4 }); // top tube
M.tube(HB, HT, 0.024, { rings: 4, seg: 12, longs: 6 });                      // head tube
for (const s of [-1, 1]) {
  M.tube(BB, [RA[0] + 0.02, RA[1], 0.065 * s], 0.012, { rings: 8, seg: 8, longs: 3, zA: 0.03 * s });   // chainstay
  M.tube(SC, [RA[0] + 0.02, RA[1] + 0.02, 0.065 * s], 0.010, { rings: 8, seg: 8, longs: 3, zA: 0.012 * s }); // seat stay
}
// fork
for (const s of [-1, 1]) M.tube([0.40, 0.64, 0.045 * s], [FA[0], FA[1], 0.05 * s], 0.013, { rings: 7, seg: 8, longs: 3 });
M.tube([0.40, 0.64, -0.05], [0.40, 0.64, 0.05], 0.018, { rings: 3, seg: 8, longs: 4 });  // fork crown
// stem + handlebar
M.tube(HT, [0.36, 0.97, 0], 0.013, { rings: 4, seg: 8, longs: 4 });
M.tube([0.36, 0.97, 0], [0.43, 0.99, 0], 0.013, { rings: 3, seg: 8, longs: 4 });
M.box([0.43, 0.99, 0], [0.04, 0.04, 0.07]);                                     // handlebar clamp
M.polyTube([[0.33, 1.00, -0.32], [0.40, 1.00, -0.18], [0.43, 0.99, 0], [0.40, 1.00, 0.18], [0.33, 1.00, 0.32]], 0.011, { seg: 8, longs: 3, ringsPer: 3 });
for (const s of [-1, 1]) M.tube([0.335, 1.0, 0.30 * s], [0.32, 1.0, 0.40 * s], 0.017, { rings: 4, seg: 8, longs: 4 }); // grips
// seatpost + saddle
M.tube(ST, [-0.27, 0.95, 0], 0.014, { rings: 4, seg: 8, longs: 4 });
M.saddle([-0.29, 0.975, 0]);
M.box([-0.27, 0.955, 0], [0.05, 0.024, 0.04]);                                  // seatpost clamp
for (const s of [-1, 1]) M.tube([-0.36, 0.966, 0.02 * s], [-0.19, 0.966, 0.02 * s], 0.004, { rings: 2, seg: 6, longs: 2 });   // saddle rails
// fenders
M.fender(RA, R + 0.035, 0.05, 1.75, 3.35);
M.fender(FA, R + 0.035, 0.05, 0.10, 1.65, true);
for (const s of [-1, 1]) {   // fender stays: attached to the axle
  M.tube([RA[0], RA[1], 0.03 * s], [RA[0] + Math.cos(2.6) * (R + 0.035), RA[1] + Math.sin(2.6) * (R + 0.035), 0.024 * s], 0.004, { rings: 2, seg: 6, longs: 2 });
  M.tube([FA[0], FA[1], 0.05 * s], [FA[0] + Math.cos(0.35) * (R + 0.035), FA[1] + Math.sin(0.35) * (R + 0.035), 0.024 * s], 0.004, { rings: 2, seg: 6, longs: 2 });
}
M.tube([0.40, 0.64, 0], [0.43, 0.72 - 0.0, 0], 0.006, { rings: 2, seg: 6, longs: 2 });   // front fender attached to the fork crown
M.tube([SC[0], SC[1], 0], [-0.3, 0.74, 0], 0.006, { rings: 2, seg: 6, longs: 2 });       // rear fender attached to the seat stays
// headlight
M.tube([0.355, 0.87, 0], [0.44, 0.88, 0], 0.007, { rings: 3, seg: 6, longs: 3 });   // light bracket (sticks out from the head tube)
M.tube([0.44, 0.88, 0], [0.49, 0.88, 0], 0.028, { rings: 3, seg: 12, longs: 6 });
M.disc([0.495, 0.88, 0], [1, 0, 0], 0.028, { rings: [0.028, 0.018, 0.008], seg: 16 });

// ---------- Drivetrain (belt + cranks) ----------
M.piece('drive');
M.ring(BB, [0, 0, 1], 0.095, 32, 0.04);      // front belt sprocket
M.ring(BB, [0, 0, 1], 0.080, 32, 0.04);
M.ring([RA[0], RA[1], 0.04], [0, 0, 1], 0.05, 24);
M.beltLines([BB[0], BB[1], 0.04], 0.095, [RA[0], RA[1], 0.04], 0.05);
for (const s of [-1, 1]) {
  const ang = s > 0 ? -1.15 : 1.99;
  const tip = [BB[0] + Math.cos(ang) * 0.17, BB[1] + Math.sin(ang) * 0.17, 0.08 * s];
  M.tube([BB[0], BB[1], 0.06 * s], tip, 0.011, { rings: 4, seg: 6, longs: 3 });
  M.box([tip[0], tip[1], tip[2] + 0.05 * s], [0.10, 0.018, 0.09]);   // pedal
}
M.tube([BB[0], BB[1], -0.07], [BB[0], BB[1], 0.07], 0.024, { rings: 3, seg: 12, longs: 6 });

// ---------- Wheels ----------
for (const [id, c] of [['wheel-r', RA], ['wheel-f', FA]]) {
  M.part(id, { anchor: c });
  M.piece(id);
  M.wheel(c, R, { hub: id === 'wheel-f' ? 0.03 : 0.0, spokes: id === 'wheel-f' ? 24 : 18, spokeFrom: id === 'wheel-f' ? 0.03 : 0.095 });
}

// ---------- Battery (hidden in the down tube): lower shell cover + cell array + management board ----------
M.part('battery', { anchor: [0.19, 0.485, 0.05], tagDir: -1 });
const dA = [BB[0] + 0.03, BB[1] + 0.03, 0], dB = [HB[0] - 0.01, HB[1] - 0.01, 0];
M.piece('battery-shell', { explode: [0.0, 0.0, 0.0] });
M.tube(dA, dB, 0.045, { rings: 14, seg: 14, longs: 6, arc: [0.58, 0.92] });    // upper half of the down tube (fixed)
M.piece('battery-cover', { explode: [-0.2, -0.165, 0.07] });
M.tube(dA, dB, 0.047, { rings: 14, seg: 10, longs: 5, arc: [-0.08, 0.58] });        // down tube lower cover (slides out)
M.piece('battery-cells', { explode: [0, 0, 0], internal: true, hot: true });
M.cells(dA, dB, 0.03, 10, 2);
M.piece('battery-bms', { explode: [0, 0, 0], internal: true });
M.board(dA, dB, 0.30, 0.62);

// ---------- Rear hub motor: left cover / stator / rotor magnet ring / right cover ----------
M.part('motor', { anchor: [RA[0], RA[1], 0.045], center: [RA[0], RA[1], 0.06] });
M.piece('motor-capL', { explode: [0, 0, -0.11] });
M.hubCap([RA[0], RA[1], -0.035], -1);
M.piece('motor-rotor', { explode: [0, 0, 0.1], axis: { c: RA, d: [0, 0, 1] }, internal: true });
M.magnetRing(RA, 0.088, 0.075, 0.05, 28);
M.piece('motor-stator', { explode: [0, 0, 0.2], axis: { c: RA, d: [0, 0, 1] }, internal: true });
M.stator(RA, 0.066, 0.03, 0.036, 24);
M.piece('motor-capR', { explode: [0, 0, 0.31] });
M.hubCap([RA[0], RA[1], 0.035], 1);

// ---------- Front hydraulic disc brake: rotor / two caliper halves / hose ----------
M.part('brakes', { anchor: [FA[0] - 0.033, FA[1] + 0.066, 0.09], center: [FA[0] - 0.036, FA[1] + 0.078, 0.08] });
M.piece('brake-rotor', { box: false, explode: [0, 0, 0.01], axis: { c: [FA[0], FA[1], 0.06], d: [0, 0, 1] } });
M.rotor([FA[0], FA[1], 0.06], 0.08);
// the caliper sits behind and above the rotor (angle AC, radius RC), its two halves clamping the rotor; when exploded the two caliper halves separate, and the pistons separate a little less than the body = pistons extended, so the pads stay either side of the rotor
const RC = 0.074, AC = 2.03, ZR = 0.06;
M.piece('brake-caliperA', { explode: [0, 0, 0.1] });  M.caliperHalf(FA, RC, AC, ZR, 1);
M.piece('brake-pistonsA', { explode: [0, 0, 0.078], hot: true }); M.pistons(FA, RC, AC, ZR, 1);
M.piece('brake-padA', { explode: [0, 0, 0.045] });     M.pad(FA, RC, AC, ZR, 1);
M.piece('brake-caliperB', { explode: [0, 0, -0.06] }); M.caliperHalf(FA, RC, AC, ZR, -1);
M.piece('brake-pistonsB', { explode: [0, 0, -0.043], hot: true }); M.pistons(FA, RC, AC, ZR, -1);
M.piece('brake-padB', { explode: [0, 0, -0.025] });    M.pad(FA, RC, AC, ZR, -1);
M.piece('brake-line', { explode: [0.0, 0.0, 0.10], box: false });
M.polyTube([[FA[0] - 0.04, FA[1] + 0.085, 0.08], [0.47, 0.60, 0.07], [0.43, 0.75, 0.07], [0.40, 0.92, 0.08], [0.36, 0.99, 0.20], [0.34, 1.00, 0.27]], 0.006, { seg: 6, longs: 2, ringsPer: 3 });
M.lever([0.34, 1.00, 0.27]);

process.stdout.write(JSON.stringify(M.toJSON()));

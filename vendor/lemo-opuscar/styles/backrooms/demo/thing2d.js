// Silhouette of "the Thing" (东西): an organic outline drawn in Canvas2D (in the film it is a billboard at the end of the corridor, always almost square-on to the camera)
// The same function is also used for the silhouette design page. Units: metres; origin = the ground between the two feet
// o = { wave: 0..1 how far the hand is raised, ph: wave phase (rad), tilt: head tilt (rad) }
const lerp = (a, b, t) => a + (b - a) * t;
const P = (x, y) => ({ x, y });
const mixP = (a, b, t) => P(lerp(a.x, b.x, t), lerp(a.y, b.y, t));

// Draw a "limb" of tapering width along a polyline (short segments with round caps and joins stacked up, so the joints come out naturally smooth)
function limb(x, pts, widths, S) {
  x.lineCap = 'round'; x.lineJoin = 'round';
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], n = 10;
    for (let k = 0; k < n; k++) {
      const t0 = k / n, t1 = (k + 1) / n, p0 = mixP(a, b, t0), p1 = mixP(a, b, t1);
      x.lineWidth = lerp(widths[i], widths[i + 1], (t0 + t1) / 2) * S;
      x.beginPath(); x.moveTo(p0.x * S, -p0.y * S); x.lineTo(p1.x * S, -p1.y * S); x.stroke();
    }
  }
}
// Hand: palm + long thin fingers (spread when waving / hanging slightly curled)
function hand(x, wr, dir, open, S) {
  const ang = Math.atan2(dir.y, dir.x), c = Math.cos(ang), s = Math.sin(ang);
  const R = (u, v) => P(wr.x + u * c - v * s, wr.y + u * s + v * c);   // u along the hand's direction, v perpendicular
  limb(x, [wr, R(.1, 0)], [.05, .06], S);                                 // palm
  const fingers = open ? [[-.045, .2, -.32], [-.016, .23, -.1], [.014, .235, .08], [.04, .2, .28]] : [[-.02, .19, -.05], [-.005, .21, 0], [.01, .2, .04], [.022, .17, .08]];
  for (const [v, len, spread] of fingers) {
    const base = R(.09, v * 1.1), mid = R(.09 + len * .55, v * 1.1 + Math.sin(spread) * len * .5), tip = R(.09 + len * (open ? .98 : .9), v * 1.1 + Math.sin(spread) * len * (open ? 1 : .6) + (open ? 0 : .015));
    limb(x, [base, mid, tip], [.02, .016, .011], S);
  }
  const th = open ? [R(.03, .03), R(.1, .09), R(.16, .12)] : [R(.03, .025), R(.09, .04), R(.13, .03)];
  limb(x, th, [.024, .018, .012], S);
}
export function drawThing(x, S, o = {}) {
  const w = o.wave ?? 0, ph = o.ph ?? 0, tilt = o.tilt ?? .28;
  x.save(); x.fillStyle = x.strokeStyle = o.color || '#0b0a09';
  // Legs (suit trousers, legs slightly wide, gathered at the ankle)
  for (const sd of [-1, 1]) {
    limb(x, [P(sd * .085, 1.27), P(sd * .1, .72), P(sd * .1, .1), P(sd * .105, .04)], [.17, .12, .095, .09], S);
    // Shoes (flat seen from the front)
    x.beginPath(); x.ellipse(sd * .11 * S, -.035 * S, .062 * S, .04 * S, 0, 0, 7); x.fill();
  }
  // Torso: shirt tail tucked into the waistband, ribcage narrow and long, shoulders narrow, high and sloping
  x.beginPath();
  const T = (px, py) => [px * S, -py * S];
  x.moveTo(...T(-.16, 1.2));
  x.bezierCurveTo(...T(-.165, 1.42), ...T(-.2, 1.62), ...T(-.2, 1.84));
  x.bezierCurveTo(...T(-.205, 1.93), ...T(-.2, 1.99), ...T(-.16, 2.02));     // left shoulder (sloping)
  x.bezierCurveTo(...T(-.1, 2.05), ...T(-.06, 2.06), ...T(-.035, 2.08));     // neckline
  x.lineTo(...T(.035, 2.085));
  x.bezierCurveTo(...T(.06, 2.06), ...T(.1, 2.05), ...T(.16, 2.02));
  x.bezierCurveTo(...T(.2, 1.99), ...T(.205, 1.93), ...T(.2, 1.84));
  x.bezierCurveTo(...T(.2, 1.62), ...T(.165, 1.42), ...T(.16, 1.2));
  x.closePath(); x.fill();
  // Collar points: two small points (so it reads as "a colleague wearing a shirt")
  for (const sd of [-1, 1]) { x.beginPath(); x.moveTo(...T(sd * .02, 2.07)); x.lineTo(...T(sd * .075, 2.035)); x.lineTo(...T(sd * .05, 2.1)); x.closePath(); x.fill(); }
  // Neck (too long, tilted to one side)
  const nb = P(0, 2.03), nt = P(Math.sin(tilt) * .1, 2.26);
  limb(x, [nb, mixP(nb, nt, .5), nt], [.085, .07, .066], S);
  // Head (a small-ish ellipse, tilted with the neck)
  x.save(); x.translate((nt.x + Math.sin(tilt) * .06) * S, -(nt.y + .085) * S); x.rotate(tilt * .9);
  x.beginPath(); x.ellipse(0, 0, .072 * S, .098 * S, 0, 0, 7); x.fill();
  x.beginPath(); x.ellipse(0, .05 * S, .05 * S, .06 * S, 0, 0, 7); x.fill();   // chin
  x.restore();
  // Left arm: hangs to the knee
  const shL = P(-.17, 1.97), elL = P(-.235, 1.43), wrL = P(-.255, .92);
  limb(x, [shL, elL, wrL], [.1, .07, .052], S);
  hand(x, wrL, P(-.01, -1), false, S);
  // Right arm: from hanging → raised and waving (forearm swings slowly left and right about the elbow)
  const shR = P(.17, 1.97);
  const elD = P(.235, 1.43), wrD = P(.255, .92);
  const elU = P(.52, 1.74), sw = Math.sin(ph) * .11;
  const wrU = P(elU.x + Math.sin(sw + .12) * .5, elU.y + Math.cos(sw + .12) * .5);
  const elR = mixP(elD, elU, w), wrR = mixP(wrD, wrU, w);
  limb(x, [shR, elR, wrR], [.1, .07, .052], S);
  const dirD = P(.01, -1), dirU = P(Math.sin(sw * 1.3 + .1), Math.cos(sw * 1.3 + .1));
  hand(x, wrR, P(lerp(dirD.x, dirU.x, w), lerp(dirD.y, dirU.y, w)), w > .5, S);
  x.restore();
}

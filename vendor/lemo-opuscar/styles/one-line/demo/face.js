// Designed backwards: first draw the final "old man's face", then cut it into segments by life stage. Coordinates = paper units, face centre (0,0), y down.
//   left ear = birth (the baby's little fist curls into the auricle; the adult's finger = left temple arm of the glasses)   top of head = bald arc, the kite string is the only hair
//   glasses = bicycle (handlebar = right eyebrow, saddle = left eyebrow, frame = both sides of the nose bridge)      mouth = first love (red: the tops of two profiles join into the upper-lip M, a smile below)
//   nose = house (ring = left nostril, round window = right nostril)                    right eye + tear = loss
//   right ear = the child (mirror of birth: his finger is gripped)                      face outline = old age; left eye = the last stroke

// ---------- helpers ----------
function smoothPts(pts) {   // Catmull-Rom → Bézier (the current point must be pts[0])
  let d = '';
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0]},${p2[1]}`;
  }
  return d;
}
// closed eyelid (‿), n eyelashes pointing down
function lid(x0, x1, y0, dip, n) {
  const N = n * 2 + 2, dir = Math.sign(x1 - x0); let d = '', prev = [x0, y0];
  for (let i = 1; i <= N; i++) {
    const u = i / N, p = [x0 + (x1 - x0) * u, y0 + dip * 4 * u * (1 - u)];
    d += ` Q ${((prev[0] + p[0]) / 2).toFixed(1)},${((prev[1] + p[1]) / 2 + dip * .08).toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    if (i % 2 === 0 && i < N) d += ` L ${(p[0] - dir * 2.5).toFixed(1)},${(p[1] + 7).toFixed(1)} L ${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    prev = p;
  }
  return d;
}
const f1 = v => v.toFixed(1);

// ---------- glasses geometry ----------
export const LX = 128, LY = -20, LR = 92;
const KK = LR * 0.5523;
const wheel = (cx, s) => {   // s=+1 starts from the left point (right lens); s=-1 starts from the right point (left lens); goes all the way round
  const x0 = cx - s * LR, cy = LY;
  return `C ${x0},${cy + KK} ${cx - s * KK},${cy + LR} ${cx},${cy + LR} C ${cx + s * KK},${cy + LR} ${cx + s * LR},${cy + KK} ${cx + s * LR},${cy}
 C ${cx + s * LR},${cy - KK} ${cx + s * KK},${cy - LR} ${cx},${cy - LR} C ${cx - s * KK},${cy - LR} ${x0},${cy - KK} ${x0},${cy}`;
};

// ---------- Birth · left ear: the adult's finger (temple arm, with fingernail) → fingertip → the baby's thumb closes over from below → four short chubby fingers wrap round → back of the fist curves into the auricle C → wrist crease → chubby little arm = earlobe ----------
// one knuckle of a baby finger (curled round the adult finger): arches roundly from (x0, yb) to (x0 - 12, yb)
const bf = (x0, yb = -74, yt = -91) => `C ${x0},${yb - 10} ${x0 - 2},${yt} ${x0 - 6},${yt} C ${x0 - 10},${yt} ${x0 - 12},${yb - 10} ${x0 - 12},${yb}`;
// the adult finger reaches from the frame into the ear, the fingertip (with nail) hidden in the fist; the thumb presses from below; four knuckles wrap roundly over the top; back of the fist curves into the auricle C; one wrist crease; chubby arm = earlobe
const BIRTH = `M -214,-70 C -244,-72 -276,-73 -294,-72 C -296,-67 -302,-66 -306,-70 C -312,-70 -316,-66 -316,-60 C -316,-54 -312,-50 -304,-50 C -298,-50 -294,-50 -290,-50
 C -296,-46 -298,-38 -294,-33 C -290,-29 -280,-30 -272,-33 C -266,-35 -262,-40 -264,-45 C -266,-49 -268,-50 -272,-50
 C -268,-58 -266,-66 -266,-74 ${bf(-266)} ${bf(-278)} ${bf(-290)} ${bf(-302)}
 C -322,-80 -334,-64 -335,-44 C -336,-18 -330,6 -322,16 C -318,21 -323,26 -319,30 C -327,42 -316,60 -298,60 C -284,60 -274,50 -270,40`;
const EAR1_TF = {};

// ---------- Kite: the line climbs along the face edge and the bald crown to the top of the head, flicks up into the only hair → kite → tail flutters in the wind → the pen "reels in" back along the tail and the hair to the top of the head → down the other half of the crown, the right eyebrow grows out of the temple ----------
function reverseC(d) {   // reverse a path made only of M + C
  const nums = d.replace(/[MC]/g, ' ').trim().split(/[\s,]+/).map(Number);
  const pts = []; for (let i = 0; i < nums.length; i += 2) pts.push([nums[i], nums[i + 1]]);
  const r = pts.slice().reverse(); let out = `M ${r[0][0]},${r[0][1]}`;
  for (let i = 1; i < r.length; i += 3) out += ` C ${r[i][0]},${r[i][1]} ${r[i + 1][0]},${r[i + 1][1]} ${r[i + 2][0]},${r[i + 2][1]}`;
  return out;
}
const DOME_L = `M -270,40 C -264,0 -262,-60 -262,-112 C -262,-200 -240,-300 -178,-386 C -132,-436 -62,-448 0,-448`;
const HAIR = `M 0,-448 C 4,-470 -10,-490 -4,-512 C 2,-534 16,-546 14,-570 C 12,-590 20,-606 30,-620`;
const KITE = `M 0,0 Q -20,-44 -36,-90 Q -17,-114 0,-132 Q 17,-112 36,-90 Q 19,-44 0,0 L -1,-4`;
const KITE_TF = { x: 30, y: -620, r: 16 };
const bow = (x, y, a = 8, h = 13) => `C ${x - a},${y - h} ${x + a},${y - h} ${x},${y} C ${x + a},${y + h} ${x - a},${y + h} ${x},${y}`;
const TAIL = `M 30,-620 C 50,-606 62,-612 78,-600 ${bow(78, -600)} C 94,-588 104,-596 120,-584 ${bow(120, -584)} C 136,-572 146,-580 162,-570`;
const DOME_R = `M 0,-448 C 62,-448 132,-436 178,-386 C 240,-300 262,-200 262,-130`;
// ---------- Bicycle · glasses: handlebar → head tube → bottom bracket → front wheel → bottom bracket → seat tube → saddle → seat tube → rear wheel → bottom bracket ----------
const BIKE = `M 262,-130 C 260,-152 250,-170 234,-180 C 214,-192 180,-190 146,-178 C 116,-168 82,-158 62,-152 C 56,-150 54,-144 56,-138
 C 48,-104 14,-62 2,-38 C 14,-36 28,-32 36,-22 ${wheel(LX, 1)} C 28,-32 14,-38 0,-38
 C -14,-62 -48,-104 -64,-140 C -68,-148 -62,-152 -54,-152 C -86,-156 -146,-170 -190,-176 C -220,-180 -238,-176 -238,-164
 C -238,-154 -228,-150 -214,-150 C -172,-148 -116,-144 -70,-142 C -50,-108 -14,-62 -2,-38 C -14,-36 -28,-32 -36,-22 ${wheel(-LX, -1)}
 C -28,-32 -14,-38 0,-38`;

// ---------- First love · mouth (red): along the left lens frame and the left nasolabial fold down to the left mouth corner → arc of the smile → right mouth corner → right half of upper lip (B's back of head) → B's profile → chins join → A's profile → left half of upper lip ----------
const FOLD_L = `C -112,90 -126,150 -136,192 C -137,200 -138,206 -138,212`;
const DOWN_NOSE = `M 0,-38 C -14,-38 -28,-32 -36,-22 C -36,18.7 -60.1,53.3 -96.5,66.5 ${FOLD_L}`;
const PS = 1.05, NY = 203;   // profile scale, the y where the nose tips touch
const A_PROF = [[-22, 28], [-11, 21], [-13, 14], [-4, 9], [-7, 5], [-2, 1], [-7, -4], [-8, -9], [0, -15], [-9, -25], [-7, -33], [-10, -44], [-19, -56], [-33, -65]]
  .map(([x, y]) => [+((x - 1.7) * PS).toFixed(2), +((y + 15) * PS + NY).toFixed(2)]);
// above: A on the left facing right, nose tip (originally (0,-15)) lands at (−1.7·PS, NY), touching B's nose tip
const B_PROF = A_PROF.map(([x, y]) => [-x, y]);
const Ac = A_PROF.at(-1), Bc = B_PROF.at(-1), Ach = A_PROF[0], Bch = B_PROF[0];
export const MOUTH_L = [-138, 212];
const SY = 266;               // lowest point of the smile arc (the two necks meet here)
const iN = 8;                 // index of the nose tip in the profile array
export const NOSE_A = A_PROF[8];
const A_LOW = A_PROF.slice(0, iN + 1), A_UP = A_PROF.slice(iN), B_LOW = B_PROF.slice(0, iN + 1), B_UP = B_PROF.slice(iN);
const neckIn = ch => ` C ${f1(ch[0] * .2)},${SY - 2} ${f1(ch[0] * .7)},${f1(ch[1] + 12)} ${ch[0]},${ch[1]}`;   // from the middle of the smile arc along the neck to the chin
const neckOut = ch => ` C ${f1(ch[0] * .7)},${f1(ch[1] + 12)} ${f1(ch[0] * .2)},${SY - 2} 0,${SY}`;
// left mouth corner → left half of smile → midpoint → A's neck, chin, mouth, nose tip → (cross where the nose tips touch) B's nose bridge, forehead, crown → right half of upper lip → right mouth corner → right half of smile → midpoint → B's neck, chin, mouth, nose tip → A's nose bridge, forehead, crown → left half of upper lip → left mouth corner
const LOVERS = `M -138,212 C -104,250 -46,${SY} 0,${SY}` + neckIn(Ach) + smoothPts(A_LOW) + smoothPts(B_UP)
  + ` C ${f1(Bc[0] + 40)},${f1(Bc[1] + 2)} 120,190 138,212 C 104,250 46,${SY} 0,${SY}` + neckIn(Bch) + smoothPts(B_LOW) + smoothPts(A_UP)
  + ` C ${f1(Ac[0] - 40)},${f1(Ac[1] + 2)} -120,190 -138,212`;

// ---------- House · nose: back up the left nasolabial fold along the same path → ring (left nostril) → left wall → pointed roof → chimney → right wall → round window (right nostril) → along the lower edge of the right lens frame into the right eye ----------
const ringAt = (cx, cy, r, fromLeft) => fromLeft
  ? `C ${cx - r},${cy - r * .9} ${cx - r * .5},${cy - r} ${cx},${cy - r} C ${cx + r * .55},${cy - r} ${cx + r},${cy - r * .55} ${cx + r},${cy} C ${cx + r},${cy + r * .55} ${cx + r * .55},${cy + r} ${cx},${cy + r} C ${cx - r * .55},${cy + r} ${cx - r},${cy + r * .55} ${cx - r},${cy}`
  : `C ${cx + r},${cy - r * .9} ${cx + r * .5},${cy - r} ${cx},${cy - r} C ${cx - r * .55},${cy - r} ${cx - r},${cy - r * .55} ${cx - r},${cy} C ${cx - r},${cy + r * .55} ${cx - r * .55},${cy + r} ${cx},${cy + r} C ${cx + r * .55},${cy + r} ${cx + r},${cy + r * .55} ${cx + r},${cy}`;
const HOUSE = `M -138,212 C -138,206 -137,200 -136,192 C -126,150 -112,90 -96.5,66.5 C -80,80 -52,92 -35,94 ${ringAt(-26, 94, 9, true)}
 L -34,68 L -45,71 L 0,24 L 12,36 L 12,26 L 21,26 L 21,45 L 45,71 L 34,68 L 35,94 ${ringAt(26, 94, 9, false)}
 C 44,82 54,62 63,45`;

// ---------- Loss · right eye: along the lens frame into the inner eye corner → closed eyelid (with lashes) → a downward hook at the outer eye corner → pen stops = tear ----------
const EYE_R = `M 63,45 C 72,32 86,16 94,2` + lid(94, 164, 2, 13, 3) + ` C 167,5 169,10 169,15`;

// ---------- Child · right ear (exact mirror of birth): crow's feet out to the lens frame → along the frame to the upper outside → his finger (right temple arm) → the baby grips it → out at the earlobe ----------
const CROW_R = `M 169,15 C 178,4 200,-8 219.65,-11.98 C 221.05,-28.1 218.2,-44.25 211.38,-58.88`;
const CHILD = BIRTH;
const EAR2_TF = { fx: -1 };

// ---------- Old age · below the right earlobe → right cheek (slightly hollow) → jaw → chin → left jaw → left cheek → left crow's feet → left eye (last stroke, closed) ----------
const OLD = `M 270,40 C 258,76 246,110 240,146 C 234,182 226,210 216,244 C 200,298 168,338 112,362 C 76,376 38,382 0,382
 C -38,382 -76,376 -112,362 C -168,338 -200,298 -216,244 C -226,210 -236,176 -242,140 C -246,110 -240,86 -226,62 C -208,34 -190,12 -164,2`
  + lid(-164, -94, 2, 13, 3);

// ---------- The child's new line (after the hand-over): starts from the end point, thin and wobbly, runs onto the blank paper to the left and draws a small crooked kite ----------
const KID = `M -94,2 C -90,26 -104,50 -126,66 C -160,92 -220,96 -276,112 C -330,128 -380,110 -430,120 C -480,130 -506,100 -520,60
 C -532,24 -522,-20 -540,-60 C -552,-90 -560,-116 -566,-140 L -604,-196 L -572,-262 L -540,-198 L -566,-140
 C -560,-120 -580,-110 -570,-96 C -562,-84 -580,-72 -570,-60`;

// segment table: time window [t0,t1] (seconds), style = the age of the line
export const SEGS = [
  { id: 'birth', style: 'child', t: [1.0, 4.9], parts: [{ d: BIRTH, tf: EAR1_TF }], slowK: 3.2, marks: [{ at: [-314, -74], t: 4.1 }] },
  { id: 'kite', style: 'child', t: [4.9, 9.7], parts: [{ d: DOME_L }, { d: HAIR }, { d: KITE, tf: KITE_TF }, { d: TAIL }, { d: reverseC(TAIL) }, { d: reverseC(HAIR) }, { d: DOME_R }], slowK: 2.6,
    marks: [{ f: .284, t: 5.9 }, { f: .364, t: 6.4 }, { f: .502, t: 7.2 }, { f: .608, t: 7.9 }, { f: .792, t: 8.9 }] },
  { id: 'bike', style: 'teen', t: [9.7, 13.9], parts: [{ d: BIKE }], slowK: 1.6 },
  { id: 'love', style: 'love', t: [13.9, 19.4], parts: [{ d: DOWN_NOSE }, { d: LOVERS }], slowK: 2.4,
    marks: [{ at: [-138, 212], t: 14.7 }, { at: [0, 266], n: 1, t: 15.3 }, { at: [NOSE_A[0], NOSE_A[1]], n: 1, t: 16.2 }, { at: [138, 212], t: 17.4 }, { at: [NOSE_A[0], NOSE_A[1]], n: 2, t: 18.5 }] },
  { id: 'house', style: 'adult', t: [19.4, 22.8], parts: [{ d: HOUSE }], slowK: 2.4 },
  { id: 'loss', style: 'adult', t: [22.8, 26.85], parts: [{ d: EYE_R }], slowK: 2.4, holds: [{ f: .999, t: 23.8, dur: 3.05 }] },
  { id: 'child', style: 'adult', t: [26.85, 30.8], parts: [{ d: CROW_R }, { d: CHILD, tf: EAR2_TF }], slowK: 3.2, marks: [{ at: [314, -74], t: 30.1 }] },
  { id: 'old', style: 'old', t: [30.8, 38.8], parts: [{ d: OLD }], slowK: 1.8 },
  { id: 'kid', style: 'kid', t: [41.7, 46.4], parts: [{ d: KID }], slowK: 1.6 },
];

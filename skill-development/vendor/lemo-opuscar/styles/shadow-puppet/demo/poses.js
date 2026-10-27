// Hou Yi (后羿) key poses (bowT/drawT = palm targets, relative to each arm's shoulder joint; bendB/bendF = elbow bend direction, +1 = elbow points back and down)
export const POSES = {
  rest:   { rot: 0, head: 0, waist: 0, legF: -.05, legB: .07, bowT: [40, 104], drawT: [-22, 112], bendB: 1, bendF: 1, draw: 0, hB: -.2 },
  stride: { rot: .1, head: -.05, waist: -.06, legF: -.36, legB: .3, bowT: [70, 70], drawT: [-62, 80], bendB: 1, bendF: 1, draw: 0, hB: -.4 },
  liang:  { rot: -.03, head: -.3, waist: .05, legF: -.3, legB: .26, bowT: [40, -122], drawT: [-112, 18], bendB: 1, bendF: 1, draw: 0, hB: 0 },
  draw:   { rot: -.05, head: -.32, waist: .03, legF: -.26, legB: .22, bowT: [104, -82], drawT: [-2, -50], bendB: 1, bendF: -1, draw: 1, arrow: true },
  spare:  { rot: .07, head: .26, waist: 0, legF: -.12, legB: .12, bowT: [64, 72], drawT: [6, 100], bendB: 1, bendF: 1, draw: 0, hB: -.5 }
};

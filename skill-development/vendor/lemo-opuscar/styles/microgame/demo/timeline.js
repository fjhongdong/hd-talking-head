// Single source of truth for the whole film: tempo grid + segment table. Picture, score, foley and subtitles all take their timing from here. (Plain JS, node can import it too)
const segs = [];
let T = 0;
function add(id, beats, bpm, extra = {}) {
  const beatT = [];
  if (Array.isArray(bpm)) {   // accelerating bar: [from, to], each beat at its midpoint tempo
    let t = T; for (let k = 0; k < beats; k++) { beatT.push(t); t += 60 / (bpm[0] + (bpm[1] - bpm[0]) * (k + .5) / beats); }
    segs.push({ id, t0: T, t1: t, beats, bpm, beatT, ...extra }); T = t;
  } else {
    const b = 60 / bpm; for (let k = 0; k < beats; k++) beatT.push(T + k * b);
    segs.push({ id, t0: T, t1: T + beats * b, beats, bpm, beat: b, beatT, ...extra }); T += beats * b;
  }
}
// Round 1, 120 BPM
add('G1', 8, 120, { kind: 'game', style: 'crayon', cmd: 'PUMP!', ok: true });
add('S1', 8, 120, { kind: 'stage' });
add('G2', 8, 120, { kind: 'game', style: 'ink', cmd: "DON'T SNEEZE!", ok: false });
add('S2', 4, 120, { kind: 'stage' });
add('G3', 8, 120, { kind: 'game', style: 'ascii', cmd: 'STRAP IN!', ok: true });
add('S3', 4, 120, { kind: 'stage' });
add('G4', 8, 120, { kind: 'game', style: 'riso', cmd: 'CATCH!', ok: true });
add('S4', 4, 120, { kind: 'stage' });
add('SPEED', 4, [120, 140], { kind: 'speed' });
// Round 2, 140 BPM
add('G5', 6, 140, { kind: 'game', style: 'pixel', cmd: 'DODGE!', ok: true });
add('S5', 2, 140, { kind: 'stage' });
add('G6', 6, 140, { kind: 'game', style: 'blueprint', cmd: 'ZIP!', ok: true });
add('S6', 2, 140, { kind: 'stage' });
add('G7', 8, 140, { kind: 'game', style: 'swiss', cmd: 'SALUTE!', ok: false });   // includes a 2-beat instant replay
add('S7', 4, 140, { kind: 'stage', dark: true });
add('BOSSIN', 4, [140, 160], { kind: 'bossin' });
// Boss 160 BPM
add('BOSS', 32, 160, { kind: 'boss', cmd: 'LAND IT!', ok: true });
add('RESULT', 10, 160, { kind: 'stage' });
add('END', 7, 160, { kind: 'end' });
export const SEGS = segs;
export const DUR = T;
export const S = Object.fromEntries(segs.map(s => [s.id, s]));
export const find = t => { for (const s of segs) if (t < s.t1) return s; return segs[segs.length - 1]; };
// absolute time of beat k within a segment (k may be fractional)
export const bt = (id, k) => { const s = S[id]; const i = Math.floor(k), f = k - i; const a = i < s.beats ? s.beatT[i] : s.t1; const b = i + 1 < s.beats ? s.beatT[i + 1] : s.t1; return a + (b - a) * f; };

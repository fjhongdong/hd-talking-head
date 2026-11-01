// story.js — timeline (single source of truth: picture, subtitles, foley and score cues are all derived from here)
// 144 BPM, 4/4: 1 beat = 5/12 s = 10 frames, 1 bar = 5/3 s; bar(b, beat) is 1-based, beat may be fractional
export const BPM = 144, BEAT = 60 / BPM, BAR = BEAT * 4;
export const bar = (b, beat = 1) => (b - 1) * BAR + (beat - 1) * BEAT;
export const NBARS = 30, DUR = bar(NBARS + 1);            // 50.0 s
export const ANIM_FPS = 12;
export const q = t => Math.floor(t * ANIM_FPS + 1e-6) / ANIM_FPS;   // characters animated on twos
export const beats = t => t / BEAT;
// Breathing: one extreme per beat (on the beat = +1 stretched, offbeat = −1 squashed), sampled on twos
export const breath = t => Math.cos(beats(q(t)) * Math.PI * 2);

// Narration (id → start time); the "bitter" in v1b is at 1.28 s, aligned to the cut to the close-up at bar(6,1)
export const VO = { v1a: bar(4) + .15, v1b: bar(6, 1) - 1.28, v2: bar(8, 1), v3: bar(11, 2), v4: bar(15, 2), v5: bar(23, 3), v6: bar(27, 2) };
// Title cards (one card can cover several voice lines): [t0, t1, text, position 'b'|'t']
export const SUBS = [
  [VO.v1a, bar(6, 1) + 1.25, 'Seven a.m., folks! And boy, is this coffee bitter!', 'b'],
  [VO.v2, VO.v2 + 1.95, "And they're off!", 'b'],
  [VO.v3, VO.v3 + 3.25, 'Up the china cabinet... what a climber!', 'b'],
  [VO.v4, VO.v4 + 2.6, 'Look out, folks... the drain!', 't'],
  [VO.v5, VO.v5 + 2.7, "Well, I'll be... sweet as pie!", 'b'],
  [VO.v6, VO.v6 + 1.95, 'Good night, folks!', 'b'],
];

// Shot list [start, end, name]
export const SHOTS = [
  [0, bar(4), 'title'],                 // title card (rolls up at 3.4, wide1 underneath)
  [bar(4), bar(6), 'wide1'],            // alarm clock, wake up, take a sip
  [bar(6), bar(7), 'bitterCU'],         // bitter!
  [bar(7), bar(8), 'wide2'],            // spots the sugar bowl, eyes meet, off they go
  [bar(8), bar(10), 'chase'],           // tracking along the counter
  [bar(10), bar(11), 'toaster'],        // toaster
  [bar(11), bar(15), 'cupboard'],       // plate xylophone → ladle slide → tilt down
  [bar(15), bar(19), 'sink'],           // whirlpool, arm stretch, silence, pull back
  [bar(19), bar(20), 'twoShot'],        // set down, pat, turn away
  [bar(20), bar(23, 1.5), 'leaving'],   // walks off, seen from behind; sugar cube hesitates, jumps
  [bar(23, 1.5), bar(24), 'sweetCU'],   // ding! sweet
  [bar(24), bar(27), 'dance'],          // pull back: the whole kitchen dances
  [bar(27), bar(29), 'iris'],           // iris closes, gets pulled shut
  [bar(29), DUR, 'end'],
];
export const shotAt = t => SHOTS.find(s => t >= s[0] && t < s[1]) || SHOTS[SHOTS.length - 1];

// Key moments
export const K = {
  roll: [bar(3, 4), bar(4)],
  ring: [bar(4), bar(4, 2.5)], wake: bar(4), yawn: [bar(4, 3), bar(4, 4.8)], dip: bar(5, 1), lick: bar(5, 2), taste: bar(5, 3),
  wah: [bar(6, 2), bar(6, 3), bar(6, 4)],
  look: bar(7), peek: [bar(7, 1.2), bar(7, 1.8)], lock: bar(7, 2), boing: bar(7, 3), windup: bar(7, 4), go: bar(8),
  shakerPass: bar(8, 3), dive: bar(9, 3), skid: [bar(9, 4), bar(10)],
  lever: bar(10), ding: bar(10, 3), blink: [bar(10, 3.6), bar(10, 4.3)],
  fallIn: bar(11), land0: bar(11, 1.5), plateCube: i => bar(11, 2) + i * BEAT / 2,
  mugHand: bar(12), mugUp: bar(12, 1.5), plateMug: i => bar(12, 2) + i * BEAT,
  cubeSpot: bar(13, 1.5), leap: bar(13, 3), slide: [bar(13, 3.4), bar(13, 4.5)], crash: bar(14),
  tilt: [bar(14), bar(15)], splash: bar(15), mugLand: bar(15, 3),
  worry: bar(16), reach: bar(16, 2), recoil: bar(16, 2.5), resolve: bar(16, 4),
  stretch: [bar(17), bar(17, 4.6)], sink: bar(17, 1.6), silence: [bar(18), bar(18, 3)], tug: bar(18, 2.4), retract: [bar(18, 3), bar(18, 3.7)],
  lower: bar(19, 2), setDown: bar(19, 3), pats: [bar(19, 3.5), bar(19, 4)], turnAway: bar(19, 4.5),
  walk: [bar(20), bar(21)], sigh: bar(21, 2), lookDown: bar(21, 3), lookUp: bar(21, 4),
  crouch: bar(22), glances: [bar(22, 2), bar(22, 2.5), bar(22, 3), bar(22, 3.5)], smile: bar(22, 3.5), hop: bar(22, 4), launch: bar(22, 4.5), plop: bar(23),
  smack: bar(23, 2), dingSweet: bar(23, 3), popUp: bar(23, 3.3),
  pull: [bar(24), bar(25)], danceEnd: bar(27),
  irisClose: [bar(27), bar(28, 2)], handOut: bar(28, 2), grab: bar(28, 2.5), shut: bar(28, 3),
  end: bar(29),
};

// Score cues (for music/score.py): t0 = first beat
export const CUES = [
  { name: 'C1_title', bars: [1, 3], key: 'F', note: 'fanfare tpt+clar unison theme, tuba oom-pah, snare; slide whistle up bar3 beat4; cymbal on bar4.1' },
  { name: 'C2_morning', bars: [4, 7], key: 'F', note: 'lazy half-time banjo+tuba, soft piano; alarm bell 4.1; muted tpt wah 6.2/6.3/6.4(long); band STOP on 7.2 (choke cymbal) hold; 7.3 boing; 7.4 snare roll' },
  { name: 'C3_chase', bars: [8, 10], key: 'F', note: 'full hot band stride; clarinet runs; tpt lead; band drops out 10.1–10.2 (only ticks); 10.3 DING + band stab' },
  { name: 'C4_xylophone', bars: [11, 14], key: 'F', note: 'thin: piano+banjo; xylophone eighths rising C D E F G A B from 11.2; tuba quarters rising from 12.2; 13.3 slide whistle down; 14.1 crash + drum fill' },
  { name: 'C5_agitato', bars: [15, 17], key: 'Dm', note: 'tuba ostinato, low clarinet trills + chromatic climb, tpt stabs, tom rolls; 17.1–17.4 long slide whistle down; HARD CUT to silence at 18.1' },
  { name: 'silence', bars: [18, 18], note: 'bar 18 beats 1–2 silent; 18.3 spring boing + one soft piano chord' },
  { name: 'C7_lonesome', bars: [19, 22], key: 'F', note: 'solo clarinet slow theme (half-note feel) + soft piano chords; bar 21 thins; bar 22 = STOP-TIME holds: 22.1 hold, woodblock ticks on 22.2/22.25/22.3/22.35 (glances), 22.4 two rising woodblocks; 23.1 plop then 1 beat silence' },
  { name: 'C8_stomp', bars: [23, 26], key: 'G', note: '23.3 xylophone DING + cymbal; from 24.1 full band out-chorus in G, loudest; accent every beat' },
  { name: 'C9_tag', bars: [27, 28], key: 'G', note: 'theme tag winding down; 28.3 final chord + low tuba (hand pulls iris shut)' },
  { name: 'C10_end', bars: [29, 30], key: 'G', note: 'short piano+clarinet coda, last long chord; projector run-out' },
];

export const CREDITS = [
  'Original score & sound effects made in code  ·  Voice: Kokoro TTS (Apache-2.0)',
  'Fonts: Shrikhand, Limelight, IM Fell English SC (SIL OFL 1.1)',
];

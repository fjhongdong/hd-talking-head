// memsprites.js — sprites inside the memories: 4-colour childhood (160×90 native), 8-bit teenagers (campfire, sitting)
import { C, GBI, sprFromRows } from './px.js';
const G4 = { k: GBI[0], d: GBI[1], l: GBI[2], w: GBI[3] };
// Little ARLO: dark hair, wooden sword; two walk frames
const KA = [[
  '...kkk....',
  '..kdddk...',
  '.kdddddk..',
  '.kddwwwk..',
  '.kdwwkwk..',
  '..kwwwwk..',
  '...kkkk...',
  '..kdddk...',
  '.kdddddk..',
  '.kwddddkl.',
  '..kllllkl.',
  '..kk.kk.l.',
  '.kk...kk..',
], [
  '...kkk....',
  '..kdddk...',
  '.kdddddk..',
  '.kddwwwk..',
  '.kdwwkwk..',
  '..kwwwwk..',
  '...kkkk...',
  '..kdddk...',
  '.kdddddkl.',
  '.kwddddkl.',
  '..kllllk..',
  '...kkkk...',
  '...kk.kk..',
]];
// Little WREN: light hair + braid; two walk frames (the scarf tail is drawn procedurally by the scene)
const KW = [[
  '...kkkk...',
  '..kllllk..',
  '.kllllllk.',
  'klllwwwwk.',
  'kllwwkwwk.',
  'klkwwwwk..',
  '.k.kkkk...',
  '..kdddddk.',
  '.kwllllk..',
  '..kllllk..',
  '.klllllk..',
  '..kk.kk...',
  '.kk...kk..',
], [
  '...kkkk...',
  '..kllllk..',
  '.kllllllk.',
  'klllwwwwk.',
  'kllwwkwwk.',
  'klkwwwwk..',
  '.k.kkkk...',
  '..kdddddk.',
  '.kwllllk..',
  '..kllllk..',
  '.klllllk..',
  '...kkkk...',
  '...kk.kk..',
]];
// Little WREN pointing into the distance
const KW_POINT = [
  '...kkkk...',
  '..kllllk..',
  '.kllllllk.',
  'klllwwwwk.',
  'kllwwkwwk.',
  'klkwwwwk..',
  '.k.kkkkkkw',
  '..kddddd..',
  '.kllllk...',
  '..kllllk..',
  '.klllllk..',
  '..kk.kk...',
  '.kk...kk..',
];
const cache = new Map();
const mk = (k, rows, map) => { if (!cache.has(k)) cache.set(k, sprFromRows(rows, map)); return cache.get(k); };
export const kidArlo = f => mk('ka' + (f & 1), KA[f & 1], G4);
export const kidWren = f => mk('kw' + (f & 1), KW[f & 1], G4);
export const kidWrenPoint = () => mk('kwp', KW_POINT, G4);

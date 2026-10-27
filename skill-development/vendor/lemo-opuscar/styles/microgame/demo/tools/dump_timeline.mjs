// node tools/dump_timeline.mjs → timeline.json (read by the score / mix scripts)
import { SEGS, DUR } from '../timeline.js';
import fs from 'fs'; import path from 'path'; import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url));
fs.writeFileSync(path.join(here, '../timeline.json'), JSON.stringify({ dur: DUR, segs: SEGS }, null, 1));
console.log('timeline.json', DUR.toFixed(3));

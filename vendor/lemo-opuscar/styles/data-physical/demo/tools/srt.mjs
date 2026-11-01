// out/cues.json → bilingual subtitle entries (one Chinese line + one English line), durations match the burned-in ones: ≥ max(1.8 s, speech + 0.6 s)
import fs from 'fs'; import path from 'path';
const dir = path.resolve(process.argv[2] || '.');
const cues = JSON.parse(fs.readFileSync(path.join(dir, 'out/cues.json'), 'utf8'));
console.log(JSON.stringify(cues.map(c => ({ t0: c.t0, t1: +Math.max(c.t1 + .6, c.t0 + 1.8).toFixed(3), text: `${c.zh}\n${c.en}` })), null, 1));

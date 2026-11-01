// Export the subtitle intervals from story.js (matching what is burned into the picture): node styles/ink-wash/demo/cues.mjs > cues.json
import { VO } from './story.js';
console.log(JSON.stringify(VO.map(v => ({ t0: v.sub[0], t1: v.sub[1], text: v.text }))));

# TalkCraft subtitles adapter

CLI:

```sh
node render.mjs --input /abs/input.json --output /abs/subtitles.webm
```

The input contract is `{schema_version: 1, canvas: {width, height, fps, frames}, cues}`. Cue and word windows are exact half-open seconds (`start <= t < end`); no hold is added. Text offsets are UTF-16 offsets, and `emphasis` is one whole phrase span per cue. The number of emphasized cues is determined by the approved content map and timing rules, not a global cap. Empty cues render transparent frames.

This adapter uses the approved TalkCraft dark translucent rounded card at bottom 350px, 48px/600 typography, `#EAF0FA` text, `#FFC94D` emphasis, and a cyan border. Emphasis keeps its laid-out width while briefly lifting 4px and glowing; horizontal scale is forbidden because it collides with neighboring punctuation and glyphs. It is adapted from upstream `Subtitles.tsx` at SHA `fee88ad65d35422220fddf56c9de9efeeee85a9c28a2ca6122dcc0bfadf42390`; exact Scribe cue timing and JSON input are adapter semantics.

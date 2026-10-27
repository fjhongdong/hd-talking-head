#!/bin/sh
# Rebuild the finished film from scratch: sh styles/pixel-rpg/demo/build.sh   (runs from any directory)
set -e
cd "$(dirname "$0")/../../.."
PY=.venv/bin/python; D=styles/pixel-rpg/demo
$PY core/tts/tts.py $D/lines.json $D/voices                 # 1. Kokoro voice-over (bm_george 0.9)
$PY core/tts/asr_check.py $D/lines.json $D/voices           # 2. whisper line-by-line check (vo4's inn/in are homophones, so the asr field is used)
$PY $D/music/score.py                                       # 3. original chip score → music/score.wav (reads timeline.json)
node core/render/events.mjs $D                              # 4. timeline → events.json (foley / narration events)
$PY $D/mix.py                                               # 5. chip foley + narration + music ducking → mix.wav
node $D/tools/subs.mjs                                      # 6. subtitles → pixel-rpg.srt (same data as the burned-in dialogue box)
node core/render/video.mjs $D --fps 24 --workers 3 --out $D/out/video24.mp4   # 7. frame-by-frame render (1308 frames, about 20–60 s)
sh core/render/mux.sh $D/out/video24.mp4 $D/mix.wav styles/pixel-rpg/pixel-rpg.mp4 24 0   # 8. mux + −14 LUFS, no grain
node core/render/still.mjs $D 0 --q poster=1 --prefix poster_ --out $D/out && cp $D/out/poster_0.jpg styles/pixel-rpg/poster.jpg
node core/render/still.mjs $D 27.5 --q nosub=1 --prefix sf_ --out $D/out && cp $D/out/sf_27.5.jpg $D/stills/styleframe.jpg
node core/render/still.mjs $D 0 --q sheet=1 --prefix sheet_ --out $D/out      # character sheet (writes out/sheet_0.jpg)

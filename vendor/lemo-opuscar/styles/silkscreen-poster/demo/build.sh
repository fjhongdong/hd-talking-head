#!/bin/sh
# Rebuild "Three Trails" from scratch: sh styles/silkscreen-poster/demo/build.sh (runs from any directory)
# To change the content: edit demo/content.json (or CONTENT=content_alt.json), then rerun this script. No narration, so no TTS needed.
set -e
cd "$(dirname "$0")/../../.."
PY=.venv/bin/python; D=styles/silkscreen-poster/demo; O=styles/silkscreen-poster
Q=""; [ -n "$CONTENT" ] && Q="content=$CONTENT"
node $D/tools/timeline.mjs $CONTENT                                   # 1. print the timeline (derived from content.json)
node core/render/events.mjs $D                                        # 2. picture events → events.json (content.json by default)
$PY $D/music/compose.py                                               # 3. score → music/score.wav + stems
$PY $D/mix.py                                                         # 4. ambience + foley + score ducking → mix.wav
$PY $D/tools/cuecheck.py                                              # 5. sync-point self-check
G=""   # machine-wide render throttling now lives in core/render/video.mjs
$G node core/render/video.mjs $D --fps 24 --workers 2 ${Q:+--q $Q} --out $D/out/video24.mp4   # 6. frame-by-frame render (throttled)
sh core/render/mux.sh $D/out/video24.mp4 $D/mix.wav $O/silkscreen-poster.mp4 24 3                                   # 7. −14 LUFS, grain 3
node core/render/still.mjs $D 33 --out $D/out/still --prefix sf_ && cp $D/out/still/sf_33.jpg $D/stills/styleframe.jpg && cp $D/out/still/sf_33.jpg $O/poster.jpg
node core/render/still.mjs $D 2.5 19.2 30.5 39.5 --q content=content_alt.json --prefix alt_ --out $D/out/alt       # 8. stills with the alternate content

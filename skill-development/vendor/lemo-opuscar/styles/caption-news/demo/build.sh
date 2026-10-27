#!/bin/sh
# Caption News — "The Bee Ledger" (蜜蜂账本): one-command build.
# sources → fonts → frames → voice (+ speech check) → subtitles cues → reading check → events → picture → mix → master → cut-downs → stills
# Needs the library set up with `setup.sh deps voice music` and the freepats / vsco2ce / vcsl sample packs.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"; export PY
OUT="$HERE/.."; NAME=caption-news
cd "$HERE"
sh tools/fetch_sources.sh                                     # raw/ (~410 MB) + audio/src/swarm.wav
sh tools/fonts.sh >/dev/null                                  # OFL subsets → fonts/
[ -s assets/fr/ed_153.jpg ] && [ -s assets/states.json ] || sh tools/prep.sh
[ -f "$LIB/core/tts/kokoro-v1.0.onnx" ] || (cd "$LIB" && sh tools/fetch.sh voice)
for l in freepats vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done
[ -f audio/vo/L13.wav ] || "$PY" "$LIB/core/tts/tts.py" audio/lines.json audio/vo
"$PY" "$LIB/core/tts/asr_check.py" audio/lines.json audio/vo --lang en
python3 tools/cues.py                                         # timeline.json → audio/cues.json (+ timing check)
cd "$LIB"
node core/render/readcheck.mjs "$HERE" --step 0.05
node core/render/events.mjs "$HERE"
node core/render/video.mjs "$HERE" --fps 30 --workers ${WORKERS:-4} --out "$HERE/out/video.mp4"
"$PY" "$HERE/audio/mix.py"
"$PY" core/render/srt.py "$HERE/audio/cues.json" "$OUT/$NAME.srt"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 30 1
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -vf scale=1280:-2 -c:v libx264 -crf 24 -preset slow -c:a aac -b:a 128k -movflags +faststart "$OUT/$NAME-small.mp4"
node core/render/still.mjs "$HERE" 22.3 --prefix poster_ --out "$HERE/stills"
cp "$HERE/stills/poster_22.3.jpg" "$OUT/poster.jpg"; mv "$HERE/stills/poster_22.3.jpg" "$HERE/stills/styleframe.jpg"
sh "$HERE/tools/final_check.sh" "$OUT/$NAME.mp4"
echo "done: $OUT/$NAME.mp4"

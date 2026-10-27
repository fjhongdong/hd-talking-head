#!/bin/sh
# Constructivist Montage — "410 Days": one-command build.
# fetch what git does not hold → prepare footage → voice (+ speech check) → reading check → picture
# → score and sound → subtitles (+ one-line check) → master → poster, styleframe → checks on the film.
# From a clean clone (library set up with `setup.sh deps voice music`) the first run also downloads:
#   the sources listed in SOURCES.jsonl (Internet Archive, Wikimedia Commons; ~95 MB)   tools/fetch_sources.sh
#   fonts (Google Fonts, OFL) and a Noto Sans SC subset                                     tools/fonts.py
#   the u2net_human_seg model (~170 MB, into ~/.rembg/models) and onnxruntime if missing    tools/kit_env.sh
#   the voice model and the vsco2ce / vcsl samples                                          tools/fetch.sh (library packs)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"
NAME=$(basename "$(dirname "$HERE")"); NAME=${NAME#demo-}         # styles/kino-montage (or a films/demo-<name> draft) → kino-montage
OUT="$HERE/.."
cd "$HERE"
[ -f raw/empires.mp4 ] && [ -f raw/brochure_zip.zip ] || sh tools/fetch_sources.sh
"$PY" tools/fonts.py
PYK=$(sh tools/kit_env.sh)                                       # a python with onnxruntime (library venv or demo/.venv)
[ -f assets/clips.json ] && [ -f assets/cut_icarus.png ] || "$PYK" tools/prep.py all
[ -f "$LIB/core/tts/kokoro-v1.0.onnx" ] && [ -f "$LIB/core/tts/voices-v1.0.bin" ] || (cd "$LIB" && sh tools/fetch.sh voice)
for l in vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done
[ -f audio/vo/L11.wav ] || "$PY" "$LIB/core/tts/tts.py" audio/lines.json audio/vo
"$PY" "$LIB/core/tts/asr_check.py" audio/lines.json audio/vo --lang en
cd "$LIB"
node core/render/readcheck.mjs "$HERE" --step 0.05
node core/render/events.mjs "$HERE"
node "$HERE/tools/cues.mjs"                                      # audio/cues.json from the page's own subtitle table
node core/render/video.mjs "$HERE" --fps 24 --workers ${WORKERS:-3} --out "$HERE/out/video.mp4"
"$PY" "$HERE/audio/mix.py"
"$PY" core/render/srt.py "$HERE/audio/cues.json" "$OUT/$NAME.srt"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 24 4
node core/render/still.mjs "$HERE" 51.0 --prefix poster_ --out "$HERE/stills"
mv "$HERE/stills/poster_51.0.jpg" "$OUT/poster.jpg"
node core/render/still.mjs "$HERE" 2.5 --prefix sf_ --out "$HERE/stills"
mv "$HERE/stills/sf_2.5.jpg" "$HERE/stills/styleframe.jpg"
"$PY" "$HERE/tools/rhythm_report.py" "$OUT/$NAME.mp4"
"$PY" "$HERE/tools/final_asr.py" "$OUT/$NAME.mp4"
echo "done: $OUT/$NAME.mp4"

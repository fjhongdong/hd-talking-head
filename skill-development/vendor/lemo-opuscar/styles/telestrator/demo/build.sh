#!/bin/sh
# Sports Telestrator — "Freeze Frame" (定格): one-command build.
# sources → frames → fonts → voice (+ speech check) → cues → reading check → picture → mix → .srt → master → stills → checks
# Needs the library set up with `setup.sh deps voice music`, the freepats / vsco2ce / vcsl sample packs, and uv (for yt-dlp).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"; export PY
OUT="$HERE/.."; NAME=telestrator
cd "$HERE"
sh tools/fetch_sources.sh                                     # raw/ (~55 MB)
sh tools/prep.sh                                              # frames a/ b/ c/ (1.5×, deblock, grade), photos, match audio
"$PY" tools/homography.py                                     # pitch lines → perspective matrices, shot positions (assets/pitch.json)
[ -s fonts/sans900.woff2 ] || python3 -I tools/fonts.py       # OFL subsets (delete fonts/*.woff2 after changing on-screen text)
[ -f "$LIB/core/tts/kokoro-v1.0.onnx" ] || (cd "$LIB" && sh tools/fetch.sh voice)
for l in freepats vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done
[ -f audio/vo/map.wav ] || "$PY" "$LIB/core/tts/tts.py" audio/lines.json audio/vo
"$PY" "$LIB/core/tts/asr_check.py" audio/lines.json audio/vo --lang en
cp audio/vo/dur.json vdur.json
"$PY" tools/cues.py                                           # timeline.json → audio/cues.json
cd "$LIB"
node core/render/readcheck.mjs "$HERE" --step 0.05
node core/render/video.mjs "$HERE" --fps 30 --workers ${WORKERS:-4} --out "$HERE/out/video.mp4"
"$PY" "$HERE/tools/mix.py"
"$PY" core/render/srt.py "$HERE/audio/cues.json" "$OUT/$NAME.srt"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 30 2
node core/render/still.mjs "$HERE" 13.6 --q nosub=1 --prefix poster_ --out "$HERE/stills"
cp "$HERE/stills/poster_13.6.jpg" "$OUT/poster.jpg"; mv "$HERE/stills/poster_13.6.jpg" "$HERE/stills/styleframe.jpg"
sh "$HERE/tools/final_check.sh" "$OUT/$NAME.mp4"
echo "done: $OUT/$NAME.mp4"

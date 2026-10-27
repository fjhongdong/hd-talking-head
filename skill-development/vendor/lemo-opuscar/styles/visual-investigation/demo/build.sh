#!/bin/sh
# Visual Investigation — "The Hindenburg: Four Minutes, 32 Seconds": one-command build.
# fetch sources → prepare frames → fonts → voice (+ speech check) → mix → checks → picture → subtitles → master → poster.
# Library set up with `setup.sh deps voice music`; ffmpeg and pdftoppm (poppler) on PATH.
# From a clean clone the first run also downloads the five sources into raw/ (~92 MB; licences in SOURCES.jsonl):
#   Universal Newsreel special release 1937-05-10 (Internet Archive), FBI Hindenburg file vol. 1 (Internet Archive),
#   three U.S. Navy / NARA photos (Wikimedia Commons), USGS Lakehurst 1:24,000 quadrangle 1947 (USGS TNM).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"
NAME=$(basename "$(dirname "$HERE")"); NAME=${NAME#demo-}
OUT="$HERE/.."
cd "$HERE"
# 1. sources (only what is missing)
FT="python3 -I tools/footage.py"
[ -f raw/univ.mpeg ] || $FT fetch archive:1937-05-10_Special_Release_Zeppelin_Explodes/1937-05-10_Special_Release_Zeppelin_Explodes.mpeg --name univ
[ -f raw/fbi01.pdf ] || $FT fetch "archive:HindenburgFBI/Hindenburg 01.pdf" --name fbi01
[ -f raw/pasq.jpg ] || $FT fetch "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/18/Hindenburg_burning%2C_1937.jpg/3840px-Hindenburg_burning%2C_1937.jpg" --name pasq --page "https://commons.wikimedia.org/wiki/File:Hindenburg_burning,_1937.jpg" --license "Public domain (U.S. Navy photo)" --credit "Gus Pasquarella, U.S. Navy"
[ -f raw/nh57973.png ] || $FT fetch "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/0c/NH_57973_Airship_HINDENBURG_Disaster%2C_6_May_1937.png/3840px-NH_57973_Airship_HINDENBURG_Disaster%2C_6_May_1937.png" --name nh57973 --page "https://commons.wikimedia.org/wiki/File:NH_57973_Airship_HINDENBURG_Disaster,_6_May_1937.png" --license "Public domain (U.S. Navy, NHHC NH 57973)" --credit "U.S. Navy / NHHC"
[ -f raw/nara518856.jpg ] || $FT fetch "https://upload.wikimedia.org/wikipedia/commons/0/05/German_airship_%22Hindenburg%22_at_Lakehurst%2C_New_Jersey._-_NARA_-_518856.jpg" --name nara518856 --page "https://commons.wikimedia.org/wiki/File:German_airship_%22Hindenburg%22_at_Lakehurst,_New_Jersey._-_NARA_-_518856.jpg" --license "Public domain (U.S. Navy / NARA 518856, U.S. federal government work)" --credit "U.S. Navy, Naval Air Station Lakehurst; National Archives (NAID 518856)"
[ -f raw/usgs1947.pdf ] || $FT fetch "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/PDF/NJ/24000/NJ_Lakehurst_254519_1947_24000_geo.pdf" --name usgs1947 --page "https://ngmdb.usgs.gov/topoview/" --license "Public domain (USGS, U.S. federal government work)" --credit "U.S. Geological Survey, Lakehurst NJ 1:24,000 quadrangle, 1947"
# 2. frames, pages, photos, map, newsreel sound clips
[ -f assets/usgs.jpg ] || sh tools/prep.sh
"$PY" -I tools/wave.py
# 3. fonts (OFL subsets of the words on screen; delete fonts/ after changing any text)
[ -f fonts/sans700.woff2 ] || python3 -I tools/fonts.py
# 4. voice, speech check, mix, subtitles
[ -f "$LIB/core/tts/kokoro-v1.0.onnx" ] && [ -f "$LIB/core/tts/voices-v1.0.bin" ] || (cd "$LIB" && sh tools/fetch.sh voice)
for l in vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done
[ -f audio/vo/v8.wav ] || "$PY" "$LIB/core/tts/tts.py" audio/lines.json audio/vo
"$PY" "$LIB/core/tts/asr_check.py" audio/lines.json audio/vo --lang en
"$PY" audio/mix.py
python3 -I tools/cues.py
# 5. checks, picture, master
cd "$LIB"
node core/render/readcheck.mjs "$HERE" --step 0.05
node core/render/events.mjs "$HERE"
node core/render/video.mjs "$HERE" --fps 30 --workers ${WORKERS:-5} --out "$HERE/out/video.mp4"
"$PY" core/render/srt.py "$HERE/audio/cues.json" "$OUT/$NAME.srt"
node "$HERE/tools/subcheck.mjs" "$OUT/$NAME.srt"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 30 0
# 6. poster (the evidence map) and gallery styleframe (the origin board)
node core/render/still.mjs "$HERE" 55.3 30.9 --prefix p_ --out "$HERE/out"
cp "$HERE/out/p_55.3.jpg" "$OUT/poster.jpg"; mkdir -p "$HERE/stills"; cp "$HERE/out/p_30.9.jpg" "$HERE/stills/styleframe.jpg"
"$PY" "$HERE/tools/final_asr.py" "$OUT/$NAME.mp4"
echo "done: $OUT/$NAME.mp4"

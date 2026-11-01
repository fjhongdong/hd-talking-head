#!/bin/sh
# Broadcast News Package — "The Week in AI" (本周 AI 四件事, "four AI stories this week"), LEMO AI NEWS week 42: one-command build.
# fonts → plates grade + map projections → voice (+ speech check) → reading check → events → picture → mix → master → .srt → stills
# Needs the library set up with `setup.sh deps voice music` and the vsco2ce / vcsl sample packs; the voice uses Doubao TTS (optional, see below).
# The two illustrative plates are committed in assets/plates/ (AI-generated, see CREDITS); tools/gen_plates.sh makes new ones.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"
OUT="$HERE/.."; NAME=news-package
for p in plate_datacenter plate_wafer; do [ -s "$HERE/assets/plates/$p.jpg" ] || { echo "missing assets/plates/$p.jpg (see STYLE.md §10 and tools/gen_plates.sh)"; exit 1; }; done
sh "$HERE/tools/fonts.sh"
[ -s "$HERE/raw/countries-50m.json" ] || { mkdir -p "$HERE/raw"; curl -fsSL -o "$HERE/raw/countries-50m.json" https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json; }
"$PY" "$HERE/tools/prep.py"
for l in vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done
cd "$LIB"
# Voice: Doubao TTS 2.0 (needs your own DOUBAO_API_KEY; cached takes in vo/.doubao/ are reused). Without a key, keep the committed
# vo/lines.json and switch to the free library voice: "$PY" core/tts/tts.py with a Kokoro Chinese voice ("lang": "cmn", zf_*/zm_*).
if [ -n "$DOUBAO_API_KEY" ]; then "$PY" -I "$HERE/tools/tts_doubao.py" "$HERE/vo/lines.json" "$HERE/vo" --speaker zh_male_jieshuoxiaoming_uranus_bigtts
else for i in v1 v2 v3 v4 v5 v6 v7 v8; do [ -s "$HERE/vo/$i.wav" ] || { echo "no voice: set DOUBAO_API_KEY, or generate vo/*.wav with core/tts/tts.py (Kokoro)"; exit 1; }; done; fi
"$PY" core/tts/asr_check.py "$HERE/vo/lines.json" "$HERE/vo" --lang zh --model small
node core/render/readcheck.mjs "$HERE" --step 0.05 || true     # previews (rundown rows) are flagged short by design: see STYLE.md §11
node core/render/events.mjs "$HERE"
node core/render/video.mjs "$HERE" --fps 30 --workers ${WORKERS:-5} --out "$HERE/out/video.mp4"
"$PY" "$HERE/mix.py"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 30 0
"$PY" "$HERE/tools/subs.py"
node core/render/still.mjs "$HERE" 18.4 --prefix poster_ --out "$HERE/stills" >/dev/null
cp "$HERE/stills/poster_18.4.jpg" "$OUT/poster.jpg"; mv "$HERE/stills/poster_18.4.jpg" "$HERE/stills/styleframe.jpg"
echo "done: $OUT/$NAME.mp4"

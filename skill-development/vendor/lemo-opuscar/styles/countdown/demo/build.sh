#!/bin/sh
# Live Countdown Split-screen — "Counting Itself Down" (自己倒数, the Chinese title): one-command build.
# fetch what git does not hold → fonts → voice (+ speech check) → frames (sync table) → subtitles (+ one-line check)
# → reading check → events → picture → score and mix → master (−14 LUFS, grain 1) → small cut → poster → speech check on the film.
# From a clean clone (library set up with `setup.sh deps voice music`) the first run also downloads:
#   the NASA clips (HTTP range reads of only the seconds used, ~400 MB) and two stills   tools/grab.py, tools/footage.py
#   fonts (Google Fonts, OFL; the Noto Sans SC subset follows the page's text)            tools/fetch_fonts.py
#   the voice model and the vsco2ce / vcsl samples                                        tools/fetch.sh (library packs)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-$(cd "$HERE/../../.." && pwd)}          # <repo>/films/<name>/demo or <repo>/styles/<slug>/demo
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
PY="$LIB/.venv/bin/python"
NAME=countdown
OUT="$HERE/.."
cd "$HERE"

# 1) footage (only what is missing). live4k is a stream-copied excerpt: its T0 (46.8 s) depends on the keyframe the cut starts on;
#    after a re-fetch, re-measure T0 (STYLE.md "Pitfalls") before trusting the sync table in tools/prep.sh.
mkdir -p raw
[ -f raw/live4k.mp4 ]   || python3 tools/grab.py "KSC-20260401-VP-JCR01-0001-Artemis_II_Live_Launch_Coverage_4K-M19183" orig 20105 75 live4k --copy
[ -f raw/fr1.mp4 ]      || python3 tools/grab.py "KSC-20260401-MH-GEB01-0002-Artemis_II_Launch_Firing_Room_1_LCC_Rover-M19183" large 330 45 fr1
[ -f raw/uas.mp4 ]      || python3 tools/grab.py "KSC-20260401-MH-JMB01-0001-Artemis_II_Launch_UAS_4K-M19183" large 0 41.9 uas --copy
[ -f raw/osb.mp4 ]      || python3 tools/grab.py "KSC-04012026-C4829" orig 28 34 osb
[ -f raw/slscam.mp4 ]   || python3 tools/grab.py "KSC-20260401-MH-AJN01-0001-Artemis_II_Launch_ISO_SLS_Launch_Vehicle_Camera_Switched_Feed_720p" orig 0 75 slscam --copy
[ -f raw/orioncam.mp4 ] || python3 tools/grab.py "art002m1200912222_Liftoff_1" large 0 53.8 orioncam --copy
[ -f raw/banana.mp4 ]   || python3 tools/grab.py "KSC-20260401-MH-CSH01-0002-Artemis_II_Launch_Banana_Creek-M19183.mp4" large 0 42.7 banana --copy
[ -f raw/walkout_0004.jpg ] || python3 tools/footage.py fetch nasa:NHQ20260401_admin_0004 --name walkout_0004 --out raw --force
[ -f raw/onepager.jpg ] || python3 tools/footage.py fetch "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/Artemis_II_One_pager_082725_508_%281974822455374%29.pdf/page1-3840px-Artemis_II_One_pager_082725_508_%281974822455374%29.pdf.jpg" \
    --name onepager --out raw --force --page "https://commons.wikimedia.org/wiki/File:Artemis_II_One_pager_082725_508_(1974822455374).pdf" \
    --license "Public domain (NASA)" --credit NASA --title "Artemis II one-pager (NASA fact sheet AIIFS-08.27.25), page 1"

# 2) fonts, voice model, samples
for f in BarlowCondensed-SemiBold.ttf Barlow-Medium.ttf IBMPlexMono-Medium.ttf NotoSansSC-500-sub.woff2 NotoSansSC-700-sub.woff2; do
  [ -f "fonts/$f" ] || { python3 tools/fetch_fonts.py; break; }
done
[ -f "$LIB/core/tts/kokoro-v1.0.onnx" ] && [ -f "$LIB/core/tts/voices-v1.0.bin" ] || (cd "$LIB" && sh tools/fetch.sh voice)
for l in vsco2ce vcsl; do [ -d "$LIB/core/audio/instruments/$l" ] || (cd "$LIB" && sh tools/fetch.sh instruments $l); done

# 3) narrator (Kokoro bf_emma) + speech check
[ -f audio/vo/n2.wav ] || "$PY" "$LIB/core/tts/tts.py" audio/lines.json audio/vo
"$PY" "$LIB/core/tts/asr_check.py" audio/lines.json audio/vo --lang en

# 4) frames: every camera to film-frame-numbered JPEGs, one grade (the sync table lives here)
[ -d frames/live ] || sh tools/prep.sh

cd "$LIB"
# 5) subtitles from the page's cues (one line per language, ≥ 1.8 s), reading check, events
node "$HERE/tools/subs.mjs" "$HERE"
"$PY" core/render/srt.py "$HERE/audio/cues.json" "$OUT/$NAME.srt"
node core/render/readcheck.mjs "$HERE" --step 0.05
node core/render/events.mjs "$HERE"
# 6) picture, sound, master
node core/render/video.mjs "$HERE" --fps 30 --workers ${WORKERS:-4} --out "$HERE/out/video.mp4"
"$PY" "$HERE/audio/mix.py"
sh core/render/mux.sh "$HERE/out/video.mp4" "$HERE/out/mix.wav" "$OUT/$NAME.mp4" 30 1
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -vf scale=1280:-2 -c:v libx264 -crf 24 -preset medium -c:a aac -b:a 160k "$OUT/$NAME-small.mp4"
# 7) poster = style frame (the nine-cell grid at T−0:04, engines lit)
node core/render/still.mjs "$HERE" 28.5 --prefix sf_ --out "$HERE/stills"
mv "$HERE/stills/sf_28.5.jpg" "$HERE/stills/styleframe.jpg"
cp "$HERE/stills/styleframe.jpg" "$OUT/poster.jpg"
# 8) listen back: Whisper on the finished film
"$PY" -I "$HERE/tools/final_asr.py" "$OUT/$NAME.mp4"
echo "done: $OUT/$NAME.mp4"

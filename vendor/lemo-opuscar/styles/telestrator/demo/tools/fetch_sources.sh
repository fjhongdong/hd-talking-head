#!/bin/sh
# Downloads raw/ (about 55 MB). Sources and licences: see SOURCES.md / SOURCES.jsonl.
#   kald.webm   Wikimedia Commons, beIN SPORTS Türkiye, CC BY 3.0 (14 s clip of the third goal)
#   yt/summary.mp4  full-match highlights published 2019-07-24 by the verified official beIN SPORTS Türkiye channel, marked CC BY on YouTube (first two goals);
#                   native 720p rendition (format 232+140), not YouTube's AI-upscaled rendition. Needs uv (uvx yt-dlp).
#   stadium.jpg Commons，Olos88，CC0      hak.jpg  Commons，Thomas Rodenbücher，CC BY 2.0
set -e
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"; mkdir -p raw/yt
UA="LemoOpuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
get() { [ -s "$2" ] || { echo "fetch $2"; curl -sSfL -A "$UA" --retry 4 --retry-delay 5 -o "$2" "$1"; }; }
get "https://upload.wikimedia.org/wikipedia/commons/2/20/Kald%C4%B1r%C4%B1m_scored_the_goal_for_a_3-3_draw_%28Be%C5%9Fikta%C5%9F-Fenerbah%C3%A7e_Derby_-_February_2019%29.webm" raw/kald.webm
get "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Vodafone_Park%2C_Istanbul_%28from_outside%29.jpg/1920px-Vodafone_Park%2C_Istanbul_%28from_outside%29.jpg" raw/stadium.jpg
get "https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Hasan_Ali_Kald%C4%B1r%C4%B1m_2013_1.jpg/500px-Hasan_Ali_Kald%C4%B1r%C4%B1m_2013_1.jpg" raw/hak.jpg
[ -s raw/yt/summary.mp4 ] || uvx yt-dlp -f "232+140/bv*[height=720][vcodec^=avc1]+ba[ext=m4a]" --no-playlist --write-info-json -o "raw/yt/summary.%(ext)s" "https://www.youtube.com/watch?v=sYfsd9Hv7hc"
ls -la raw raw/yt | grep -v "^total"

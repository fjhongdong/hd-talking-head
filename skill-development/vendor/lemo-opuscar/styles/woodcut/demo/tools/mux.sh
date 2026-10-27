#!/bin/sh
# Final mux (this film's version): first run core/render/mux.sh (two-pass loudnorm −14 LUFS + grain), then re-encode at CRF 28 + tune grain.
# The woodcut's fine hatching + per-frame ink and grain push a CRF 19 file to 326 MB; CRF 28 shows no difference in a 1:1 crop comparison, at 93 MB.
# Usage: sh tools/mux.sh video.mp4 mix.wav out.mp4 [fps] [grain]
set -e
V="$1"; A="$2"; O="$3"; FPS="${4:-24}"; GR="${5:-6}"
R="$(cd "$(dirname "$0")/../../../.." && pwd)"; TMP="$(dirname "$V")/master_crf19.mp4"
sh "$R/core/render/mux.sh" "$V" "$A" "$TMP" "$FPS" "$GR"
ffmpeg -y -loglevel error -i "$TMP" -c:v libx264 -preset slow -crf "${CRF:-28}" -tune grain -c:a copy -movflags +faststart "$O"
rm -f "$TMP"; ls -la "$O" | awk '{printf "%s  %.1f MB\n", $9, $5/1e6}'

#!/bin/zsh
# Concatenate segments → light grain → mix in the score → final film
# Usage: ./mux.sh [output path]
#   OUTDIR=out_ej (default, English/Japanese version) → default output ../pictogram-motion.mp4 (= styles/pictogram-motion/pictogram-motion.mp4)
#   OUTDIR=out    (Chinese version)                 → default output out/pictogram-motion_zh.mp4
set -e
cd "${0:A:h}"
SEG="${OUTDIR:-out_ej}"
if [[ "$SEG" == "out_ej" ]]; then DEF="../pictogram-motion.mp4"; else DEF="$SEG/pictogram-motion_zh.mp4"; fi
OUT="${1:-$DEF}"
ffmpeg -y -loglevel error -f concat -safe 0 -i $SEG/list.txt -i music/music.wav \
  -vf "tpad=stop_duration=2:stop_mode=clone,noise=c0s=4:c0f=t+u,format=yuv420p" \
  -c:v libx264 -preset slow -crf 14 -profile:v high -r 60 -g 120 \
  -c:a aac -b:a 320k -ar 48000 -map 0:v -map 1:a -shortest -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"

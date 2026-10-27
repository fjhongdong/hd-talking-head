#!/bin/sh
# assemble the finished film: sh styles/watercolor/demo/mux.sh [out.mp4]   (default styles/watercolor/watercolor.mp4; measured about 70 s with preset slow)
# inputs: out/list.txt + out/seg_*.mp4 (output of node render.mjs video 8), mix.wav (output of python mix.py)
# parameters were reverse-engineered from the existing film: x264 SEI = preset slow / crf 16 / keyint 120; no grain added;
# audio single-pass loudnorm I=-14 TP=-1 → measured -14.2 LUFS / peak -1.0 dBFS, matching the film.
case "$1" in "") O="";; /*) O="$1";; *) O="$(pwd)/$1";; esac   # relative paths resolve against the calling directory
cd "$(dirname "$0")"
O="${O:-../watercolor.mp4}"
ffmpeg -y -loglevel error -f concat -safe 0 -i out/list.txt -i mix.wav \
  -map 0:v -map 1:a -c:v libx264 -preset slow -crf 16 -g 120 \
  -af "loudnorm=I=-14:TP=-1:LRA=11,aresample=48000" -c:a aac -b:a 256k \
  -movflags +faststart -shortest "$O"
echo "$O"
ffmpeg -hide_banner -nostats -i "$O" -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I|LRA|Peak):" | head -3

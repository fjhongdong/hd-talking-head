#!/bin/sh
# Concatenates the segments produced by `render.mjs video` + mixes in music.wav → finished film
# Usage: sh finish.sh [out.mp4]   default output ../game-show.mp4 (this overwrites the library's finished film; for test runs pass another path, e.g. out/test.mp4)
# Settings match the finished film: x264 slow crf16 / AAC 256k 48 kHz / two-pass loudnorm → −14 LUFS
# AUDIO_FROM=old_film.mp4 sh finish.sh …  → no remix, copies the old film's audio track as-is (for re-rendering part of the picture while keeping the audio unchanged)
set -e
cd "$(dirname "$0")"
O="${1:-../game-show.mp4}"
ffmpeg -y -loglevel error -f concat -safe 0 -i out/list.txt -c copy out/video_noaudio.mp4
if [ -n "$AUDIO_FROM" ]; then
  ffmpeg -y -loglevel error -i out/video_noaudio.mp4 -i "$AUDIO_FROM" -map 0:v -map 1:a -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -c:a copy -movflags +faststart "$O"
  echo "$O (audio copied from $AUDIO_FROM)"; exit 0
fi
J=$(ffmpeg -hide_banner -nostats -i music.wav -af loudnorm=I=-14:TP=-1.2:LRA=11:print_format=json -f null - 2>&1 | sed -n '/{/,/}/p')
g() { echo "$J" | /usr/bin/grep "\"$1\"" | sed 's/.*: "\(.*\)".*/\1/'; }
LN="loudnorm=I=-14:TP=-1.2:LRA=11:measured_I=$(g input_i):measured_TP=$(g input_tp):measured_LRA=$(g input_lra):measured_thresh=$(g input_thresh):offset=$(g target_offset):linear=true"
ffmpeg -y -loglevel error -i out/video_noaudio.mp4 -i music.wav \
  -filter_complex "[1:a]$LN,aresample=48000[a]" -map 0:v -map "[a]" \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -c:a aac -b:a 256k -movflags +faststart -shortest "$O"
echo "$O"
ffmpeg -hide_banner -nostats -i "$O" -af ebur128 -f null - 2>&1 | /usr/bin/grep -E "^\s+(I|Peak):" | head -2

#!/bin/sh
# prepare the score source files (music/*.mp3 / *.wav are ignored by the root .gitignore; run this first in a fresh clone)
# Scott Buckley《Wildflowers》CC BY 4.0 — https://www.scottbuckley.com.au/library/
# both wavs are decoded directly from the mp3:
#   Wildflowers.wav = 22.05 kHz mono, for beat and self-similarity analysis in analyze.py / jump.py / lag.py
#   wf48.wav        = 48 kHz stereo, for the jump cut in edit.py → score.wav
cd "$(dirname "$0")"
[ -f Wildflowers.mp3 ] || curl -L -o Wildflowers.mp3 https://www.scottbuckley.com.au/library/wp-content/uploads/2025/12/Wildflowers.mp3
[ -f Wildflowers.wav ] || ffmpeg -y -loglevel error -i Wildflowers.mp3 -ac 1 -ar 22050 Wildflowers.wav
[ -f wf48.wav ] || ffmpeg -y -loglevel error -i Wildflowers.mp3 -ar 48000 wf48.wav
ls -la Wildflowers.mp3 Wildflowers.wav wf48.wav

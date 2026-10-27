#!/bin/sh
# Shouted voice calls: macOS `say` English system voices → ffmpeg pitch shift without tempo change → 44.1 kHz mono wav
# Regenerates the calls from voices/lines*.txt (measured: title.wav pitch 204 Hz matches the committed file; of 40 lines, 36 are within ≤ 30 ms in duration, the rest ≤ 40 ms).
# Each line of lines*.txt: name|voice|rate (say -r)|pitch factor|line
# Usage: sh make_voices.sh [output dir]   default out/voices_regen/ (does not overwrite voices/; copy over by hand once checked)
set -e
cd "$(dirname "$0")"
OD="${1:-out/voices_regen}"; mkdir -p "$OD"
cat voices/lines.txt voices/lines2.txt voices/lines3.txt | while IFS='|' read -r NAME VOICE RATE PITCH TEXT; do
  [ -z "$NAME" ] && continue
  say -v "$VOICE" -r "$RATE" -o "$OD/$NAME.aiff" "$TEXT"
  # say outputs 22050 Hz; asetrate raises the pitch, atempo restores the duration (silence not trimmed: the original files were not trimmed either)
  ffmpeg -y -loglevel error -i "$OD/$NAME.aiff" -af "asetrate=22050*$PITCH,aresample=44100,atempo=1/$PITCH" -ac 1 -ar 44100 "$OD/$NAME.wav"
  rm "$OD/$NAME.aiff"; echo "$NAME ($VOICE)"
done

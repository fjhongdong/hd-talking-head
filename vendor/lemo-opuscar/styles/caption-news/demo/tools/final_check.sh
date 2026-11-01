#!/bin/sh
# Checks on the finished file: loudness (EBU R128), blank frames, and speech-to-text of the final mix.
F="$1"; LIB=${LIB:-$(cd "$(dirname "$0")/../../../.." && pwd)}
ffmpeg -hide_banner -nostats -i "$F" -af ebur128=peak=true -f null - 2>&1 | grep -A12 "Summary" | grep -E "I:|Peak:|LRA:"
echo "black frames:"; ffmpeg -hide_banner -nostats -i "$F" -vf blackdetect=d=0.1:pix_th=0.06 -an -f null - 2>&1 | grep blackdetect || echo "  none"
"$LIB/.venv/bin/python" - "$F" <<'PY'
import sys, subprocess, tempfile, os
from faster_whisper import WhisperModel
w = tempfile.mktemp(suffix='.wav'); subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', sys.argv[1], '-ac', '1', '-ar', '16000', w], check=True)
segs, _ = WhisperModel(os.environ.get('WHISPER_MODEL', 'base.en'), compute_type='int8').transcribe(w, language='en')
for s in segs: print(f'  {s.start:5.1f}-{s.end:5.1f} {s.text.strip()}')
os.remove(w)
PY

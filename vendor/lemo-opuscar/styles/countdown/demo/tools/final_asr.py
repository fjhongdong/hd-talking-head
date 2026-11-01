"""Listen-back on the finished film: transcribe the film's soundtrack with faster-whisper and print it segment by segment (film seconds), to confirm both the source audio and the narration are intelligible in the mix.
Usage: $LIB/.venv/bin/python -I tools/final_asr.py <film.mp4> [model=small.en]"""
import subprocess, sys, tempfile, os
from faster_whisper import WhisperModel
mp4 = sys.argv[1]; model = sys.argv[2] if len(sys.argv) > 2 else "small.en"
wav = os.path.join(tempfile.mkdtemp(), "a.wav")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-ac", "1", "-ar", "16000", wav], check=True)
segs, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(wav, language="en", vad_filter=False)
for s in segs: print(f"[{s.start:6.2f}–{s.end:6.2f}] {s.text.strip()}")

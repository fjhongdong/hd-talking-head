from faster_whisper import WhisperModel
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))   # voices/ is relative to demo/
import glob
m = WhisperModel("base.en", device="cpu", compute_type="int8")
for f in sorted(glob.glob("voices/v*.wav")):
    segs, _ = m.transcribe(f, beam_size=5)
    print(f[-7:-4], " ".join(s.text.strip() for s in segs))

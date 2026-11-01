"""Contact sheet: python3 tools/sheet.py <video> <out.jpg> [interval_s=2] [start_s=0] [end_s]"""
import sys, subprocess, tempfile, os, glob
from PIL import Image, ImageDraw
src, out = sys.argv[1], sys.argv[2]
step = float(sys.argv[3]) if len(sys.argv) > 3 else 2; t0 = float(sys.argv[4]) if len(sys.argv) > 4 else 0
t1 = sys.argv[5] if len(sys.argv) > 5 else None
d = tempfile.mkdtemp()
cmd = ["ffmpeg", "-v", "error", "-ss", str(t0)] + (["-to", t1] if t1 else []) + ["-i", src, "-vf", f"fps=1/{step},scale=320:-2", f"{d}/%04d.jpg"]
if t1: cmd = ["ffmpeg", "-v", "error", "-ss", str(t0), "-i", src, "-t", str(float(t1) - t0), "-vf", f"fps=1/{step},scale=320:-2", f"{d}/%04d.jpg"]
subprocess.run(cmd, check=True)
fs = sorted(glob.glob(f"{d}/*.jpg")); ims = [Image.open(f) for f in fs]
w, h = ims[0].size; cols = 8; rows = (len(ims) + cols - 1) // cols
S = Image.new("RGB", (cols * w, rows * h))
for i, im in enumerate(ims):
    x, y = (i % cols) * w, (i // cols) * h; S.paste(im, (x, y))
    dr = ImageDraw.Draw(S); t = t0 + i * step
    dr.rectangle([x, y, x + 64, y + 16], fill=(0, 0, 0)); dr.text((x + 3, y + 2), f"{t:.1f}", fill=(255, 255, 0))
S.save(out, quality=80); print(out, len(ims))

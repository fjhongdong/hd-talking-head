"""Look at a video's content remotely through the Commons video thumbnail endpoint (seek=seconds), without downloading the whole file: python3 peek.py "File:X.webm" name duration_s count out_dir"""
import sys, time, subprocess, os, hashlib, urllib.request, urllib.parse
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
t, name, dur, n, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
fn = t.removeprefix("File:").replace(" ", "_"); h = hashlib.md5(fn.encode()).hexdigest(); q = urllib.parse.quote(fn)
os.makedirs(out, exist_ok=True); fr = []
for k in range(n):
    ts = dur * (k + 0.5) / n; f = f"{out}/_{name}_{k:02d}.jpg"
    url = f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/330px-seek={int(ts)}-{q}.jpg"
    for a in range(6):
        try:
            open(f, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()); break
        except Exception as e:
            print(k, e, file=sys.stderr); time.sleep(10 * (a + 1))
    else: continue
    fr.append((f, ts)); time.sleep(0.7)
from PIL import Image, ImageDraw
cols = 6; rows = (len(fr) + cols - 1) // cols
sheet = Image.new("RGB", (cols * 330, rows * 186)); dr = ImageDraw.Draw(sheet)
for i, (f, ts) in enumerate(fr):
    im = Image.open(f).convert("RGB"); im.thumbnail((330, 186)); x, y = (i % cols) * 330, (i // cols) * 186
    sheet.paste(im, (x, y)); dr.rectangle([x, y, x + 44, y + 16], fill=(0, 0, 0)); dr.text((x + 3, y + 2), f"{ts:.0f}", fill=(255, 230, 0))
sheet.save(f"{out}/peek_{name}.jpg", quality=85)
for f, _ in fr: os.remove(f)
print(f"{out}/peek_{name}.jpg", len(fr))

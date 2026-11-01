"""Per-second contact sheet of a source: python tools/secsheet.py raw/x.mp4 out.jpg [start end step]"""
import sys, subprocess
from PIL import Image, ImageDraw
src, out = sys.argv[1], sys.argv[2]
a = float(sys.argv[3]) if len(sys.argv) > 3 else 0
dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src], capture_output=True, text=True).stdout)
b = float(sys.argv[4]) if len(sys.argv) > 4 else dur - .1
st = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
W, H, cols = 320, 180, 8; tiles = []
t = a
while t <= b:
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t}', '-i', src, '-vf', f'scale={W}:{H}', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    if len(raw) == W * H * 3: tiles.append((f'{t:.1f}', Image.frombytes('RGB', (W, H), raw)))
    t += st
rows = (len(tiles) + cols - 1) // cols
S = Image.new('RGB', (W * cols, H * rows)); d = ImageDraw.Draw(S)
for i, (lab, im) in enumerate(tiles):
    x, y = (i % cols) * W, (i // cols) * H; S.paste(im, (x, y)); d.rectangle([x, y, x + 40, y + 13], fill=0); d.text((x + 2, y + 1), lab, fill=(255, 255, 0))
S.save(out, quality=80); print(out, len(tiles))

#!/usr/bin/env python3
"""Fonts (all SIL OFL 1.1, from github.com/google/fonts): fetch what is missing, then subset Noto Sans SC
to the characters the film uses (page + subtitles), keeping its weight axis.
    python tools/fonts.py          (needs fontTools + brotli: the library .venv has both)
"""
import re, json, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
F = HERE / "fonts"
F.mkdir(exist_ok=True)
GF = "https://github.com/google/fonts/raw/main/ofl/"
NEED = {
    "NotoSansSC[wght].ttf": "notosanssc/NotoSansSC%5Bwght%5D.ttf", "OFL-NotoSansSC.txt": "notosanssc/OFL.txt",
    "Oswald[wght].ttf": "oswald/Oswald%5Bwght%5D.ttf", "OFL-Oswald.txt": "oswald/OFL.txt",
    "SpaceMono-Bold.ttf": "spacemono/SpaceMono-Bold.ttf", "OFL-SpaceMono.txt": "spacemono/OFL.txt",
}
for name, path in NEED.items():
    if not (F / name).exists():
        print("fetch", name)
        (F / name).write_bytes(urllib.request.urlopen(GF + path, timeout=120).read())

text = (HERE / "index.html").read_text() + json.dumps(json.load(open(HERE / "audio/lines.json")), ensure_ascii=False)
chars = sorted({c for c in text if ord(c) > 0x2000} | set("0123456789,.·—–-:;!?()/%+=×½ ") | {chr(c) for c in range(0x20, 0x7f)})
(F / "chars.txt").write_text("".join(chars))
from fontTools import subset
opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["*"]
fnt = subset.load_font(str(F / "NotoSansSC[wght].ttf"), opts)
s = subset.Subsetter(opts); s.populate(text="".join(chars)); s.subset(fnt)
subset.save_font(fnt, str(F / "NotoSansSC-sub.woff2"), opts)
print("NotoSansSC-sub.woff2", (F / "NotoSansSC-sub.woff2").stat().st_size // 1024, "KB,", len(chars), "chars")

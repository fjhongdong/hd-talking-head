#!/usr/bin/env python3
"""raw/ -> assets/ : one shared print grade for every source, archive-film clips as JPEG
sequences, brochure pages and crops, photographs and photomontage cut-outs.

    python tools/prep.py [clips|docs|photos|cuts|all]      (numpy, pillow, scipy; onnxruntime for cuts)

Grade ("constructivist print"): luminance -> percentile stretch -> S-curve ->
mapped between warm ink #141210 and paper #EDE4D0, so red #D52B1E sits on top as the only colour.
"""
import subprocess, shutil, sys, json, io, zipfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent.parent
RAW, OUT = HERE / "raw", HERE / "assets"
OUT.mkdir(exist_ok=True)
INK = np.array([20, 18, 16], np.float32)
PAPER = np.array([237, 228, 208], np.float32)
FPS = 24


def tone(x, s=0.32):
    """x 0..1 -> S-curve (contrast up, like a halftone print of a press photo)."""
    return np.clip(x + s * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2, 0, 1)


def duo(g):
    return (INK + (PAPER - INK) * g[..., None]).astype(np.uint8)


def grade_arr(a, lo=0.8, hi=99.4, s=0.32, p=None):
    if p is None:
        p = np.percentile(a, [lo, hi])
    return tone(np.clip((a - p[0]) / max(1, p[1] - p[0]), 0, 1), s)


def grade(im, **k):
    return Image.fromarray(duo(grade_arr(np.asarray(im.convert("L"), np.float32), **k)), "RGB")


# ----------------------------------------------------------------------------- clips
# "Empires of Steel" (American Bridge Co. / Pathescope, 1930-31), 720x536 @29.97, a 16 mm transfer.
# Windows (seconds in the source) picked from 1 fps contact sheets. Width: 960 (1.36x) or 1440 (2.05x),
# both under the 2.5x ceiling for archive film. Every clip is cropped 8 px to lose the gate edge.
CLIPS = {
    #  name        start   dur   width    what
    "rider":     (515.00, 3.6, 1440),   # a man rides the hook on a diagonal girder into the sky
    "derrtop":   (481.00, 2.0, 960),    # derricks on the tower top, silhouette
    "boom":      (492.50, 2.0, 960),    # a derrick boom swings against the sky
    "climb":     (507.50, 2.0, 960),    # a worker on the steel, silhouette
    "excav":     (88.00, 2.5, 1440),    # the site from above: rock, derricks, trucks
    "truck":     (100.30, 2.5, 960),    # a truck brings steel up 34th Street, from above
    "grillage":  (114.00, 2.5, 1440),   # men guide a steel grillage onto its footing
    "billet":    (126.20, 2.0, 960),    # the grillage set, close
    "colstreet": (150.00, 2.0, 960),    # a column arrives on a truck; hoist over the street
    "beamswing": (163.50, 2.0, 960),    # a beam swings in over the sidewalk shed
    "bolting":   (241.20, 2.5, 960),    # men bolt the foot of a riveted column
    "colrise":   (248.40, 2.5, 1440),   # a heavy column section goes up on the derrick
    "floorbeam": (259.20, 2.0, 960),    # a floor beam swings in against the next building
    "beamset":   (267.00, 2.0, 960),    # beams being set from a derrick
    "gridframe": (281.00, 2.0, 960),    # the frame from above, columns and beams
    "field":     (299.80, 4.0, 1440),   # steel laid out flat, men walking across it (top-down)
    "facade":    (330.20, 3.5, 960),    # the facade from above, floor after floor
    "highmen":   (357.20, 3.0, 960),    # workers on a beam high up, city behind
    "edge":      (372.20, 2.5, 960),    # two men on the edge of a floor, against the sky
    "risetower": (412.00, 4.0, 960),    # looking up: the steel tower rising above the stone
    "skyline":   (450.00, 3.0, 1440),   # the tower over Manhattan
    "dome":      (546.80, 3.0, 960),    # the mooring-mast steel with the flag
    "tower":     (526.00, 4.0, 1440),   # the finished tower in clouds
    "deco":      (612.00, 3.0, 1440),   # looking up the finished shaft (stone and steel strips)
    "finished":  (600.50, 3.0, 1440),   # the finished tower over the city
}
SRC = RAW / "empires.mp4"


def clips(only=None):
    meta = json.loads((OUT / "clips.json").read_text()) if (OUT / "clips.json").exists() else {}
    for k, (ss, dur, w) in CLIPS.items():
        if only and k not in only: continue
        d = OUT / k
        shutil.rmtree(d, ignore_errors=True); d.mkdir()
        h = round(w * 520 / 704 / 2) * 2
        vf = (f"crop=704:520:8:8,hqdn3d=2:2:4:4,scale={w}:{h}:flags=lanczos,"
              f"unsharp=5:5:0.45:5:5:0,fps={FPS},format=gray")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", str(SRC),
                        "-vf", vf, str(d / "%03d.png")], check=True)
        files = sorted(d.glob("*.png"))
        stack = np.concatenate([np.asarray(Image.open(f), np.float32).ravel()[::97] for f in files])
        p = np.percentile(stack, [0.7, 99.5])            # one level-set per clip: no pumping
        for i, f in enumerate(files):
            a = np.asarray(Image.open(f), np.float32)
            Image.fromarray(duo(grade_arr(a, p=p)), "RGB").save(d / f"{i:03d}.jpg", quality=84)
            f.unlink()
        meta[k] = {"n": len(files), "w": w, "h": h, "src": ss}
        print(k, len(files), "frames", w, "x", h)
    (OUT / "clips.json").write_text(json.dumps(meta, indent=1))


def stills():
    """single graded frames (full source resolution x1.5) for the photomontage tower and the turn."""
    S = {"st_rider": 516.4, "st_highmen": 361.0, "st_edge": 374.5, "st_field": 302.0, "st_grid": 286.0,
         "st_colrise": 250.0, "st_facade": 344.0, "st_bolting": 243.0, "st_beamset": 270.0,
         "st_sitter": 378.5, "st_derrtop": 484.0, "st_climb": 512.0, "st_window": 388.0, "st_grillage": 118.0}
    for k, t in S.items():
        tmp = OUT / "_tmp.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(SRC), "-frames:v", "1",
                        "-vf", "crop=704:520:8:8,hqdn3d=2:2:4:4,scale=1056:780:flags=lanczos,unsharp=5:5:0.4:5:5:0",
                        str(tmp)], check=True)
        grade(Image.open(tmp), lo=0.7, hi=99.5).save(OUT / f"{k}.jpg", quality=88)
        tmp.unlink()
        print("still", k)


# ----------------------------------------------------------------------------- docs
# What Everybody Wants to Know About Empire State (Empire State, Inc., 1931), Columbia University Libraries.
def docs():
    z = zipfile.ZipFile(RAW / "brochure_zip.zip")
    for n in sorted(n for n in z.namelist() if n.endswith(".jp2")):
        idx = int(n[-8:-4])
        im = Image.open(io.BytesIO(z.read(n))).convert("L")
        im = grade(im, lo=0.5, hi=99.0, s=0.18)          # documents keep their paper
        im.thumbnail((2200, 2200), Image.LANCZOS)
        im.save(OUT / f"doc{idx}.jpg", quality=88)
        print("doc", idx, im.size)
    d2 = Image.open(OUT / "doc2.jpg")
    # the brochure's own height comparison: four outlines drawn to one scale, lying on their side
    # (tip to the left, ground line at x~2101). Crop each with its label, turn it upright, key the paper.
    # the crops end on the ground line, so after the turn every outline stands on its bottom edge and
    # all four keep the brochure's common scale (px per foot is the same). Labels are set in the page.
    BOX = {"woolworth": (1470, 210, 2104, 370), "eiffel": (1300, 660, 2104, 1000),
           "chrysler": (1250, 1280, 2104, 1470), "empire": (1085, 1780, 2104, 2030)}
    for k, (l, t, r, b) in BOX.items():
        c = d2.crop((l, t, r, b)).rotate(-90, expand=True)    # clockwise: the tip points up
        g = np.asarray(c.convert("L"), np.float32)
        a = np.clip((205 - g) / 90, 0, 1)                     # ink -> opaque, paper -> clear
        rgba = np.dstack([np.broadcast_to(INK, g.shape + (3,)), a * 255]).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(OUT / f"bld_{k}.png")
        print("outline", k, c.size)


# ----------------------------------------------------------------------------- photos + cut-outs
U2 = Path.home() / ".rembg/models/u2net_human_seg/u2net_human_seg.onnx"
_sess = None


def human_mask(im):
    """u2net_human_seg (onnxruntime) on an RGB PIL image -> float mask 0..1 at image size."""
    global _sess
    import onnxruntime as ort
    if _sess is None:
        _sess = ort.InferenceSession(str(U2), providers=["CPUExecutionProvider"])
    x = np.asarray(im.convert("RGB").resize((320, 320), Image.LANCZOS), np.float32) / 255.0
    x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    m = _sess.run(None, {_sess.get_inputs()[0].name: x})[0][0, 0]
    m = (m - m.min()) / max(1e-6, m.max() - m.min())
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize(im.size, Image.BICUBIC), np.float32) / 255


def finish_cut(im, mk, name, border=7):
    from scipy import ndimage
    lab, n = ndimage.label(np.asarray(mk) > 127)
    if n > 1:
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        mk = Image.fromarray(((lab == 1 + int(np.argmax(sizes))) * 255).astype(np.uint8))
    a_in = np.asarray(mk.filter(ImageFilter.GaussianBlur(1.0)), np.float32) / 255
    a_out = np.asarray(mk.filter(ImageFilter.MaxFilter(2 * border + 1)).filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255
    g = np.asarray(grade(im), np.float32)
    rgb = g * a_in[..., None] + PAPER * (1 - a_in[..., None])          # scissor border = paper
    rgba = np.dstack([rgb, a_out * 255]).astype(np.uint8)
    ys, xs = np.nonzero(a_out > 0.02)
    Image.fromarray(rgba, "RGBA").crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)).save(OUT / f"cut_{name}.png")
    print("cut", name)


def cutout(src, name, box, thr=0.5):
    """crop `box` (fractions l,t,r,b) -> grade -> human mask -> PNG with a paper-white scissor border."""
    im = Image.open(src); W, H = im.size
    im = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
    m = human_mask(im)
    finish_cut(im, Image.fromarray(((m > thr) * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5)), name)



PHOTOS = {"icarus": "icarus", "workman": "nara_workman", "sitter": "esb_met"}


def find(stem):
    c = sorted(RAW.glob(stem + ".*"))
    return c[0] if c else None


def photos():
    for k, stem in PHOTOS.items():
        f = find(stem)
        if not f: print("missing", k); continue
        im = Image.open(f); im.thumbnail((2400, 2400), Image.LANCZOS)
        grade(im).save(OUT / f"ph_{k}.jpg", quality=88)
        print("photo", k, im.size)


CUTS = [  # (raw stem, name, crop box l,t,r,b as fractions), chosen from the contact sheet
    ("icarus", "icarus", (0.28, 0.0, 0.62, 0.66)),
    ("nara_workman", "workman", (0.14, 0.26, 0.52, 0.97)),
    ("esb_met", "sitter", (0.24, 0.30, 0.52, 0.97)),
]


def cuts():
    for stem, name, box in CUTS:
        f = find(stem)
        if f: cutout(f, name, box)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("clips", "all"): clips(sys.argv[2:] or None)
    if what in ("stills", "all"): stills()
    if what in ("docs", "all"): docs()
    if what in ("photos", "all"): photos()
    if what in ("cuts", "all"): cuts()


def bldmeta():
    """first opaque row of each outline (its tip) -> assets/bld.json, so the page can stand them to scale."""
    m = {}
    for k in ("woolworth", "eiffel", "chrysler", "empire"):
        a = np.asarray(Image.open(OUT / f"bld_{k}.png"))[..., 3]
        rows = np.nonzero(a.max(1) > 100)[0]; cols = np.nonzero(a.max(0) > 100)[0]
        m[k] = {"w": a.shape[1], "h": a.shape[0], "tip": int(rows[0]), "x0": int(cols[0]), "x1": int(cols[-1])}
    (OUT / "bld.json").write_text(json.dumps(m, indent=1)); print(m)


if __name__ == "__main__" and (sys.argv[1:2] == ["docs"] or sys.argv[1:2] == ["all"] or sys.argv[1:2] == []):
    bldmeta()

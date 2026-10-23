#!/usr/bin/env python3
"""Calibrate bottom-window avatars for B-roll segments from the edited A-roll.

Usage:
  python3 calibrate_avatars.py --job-context ctx --windows 24.04,32.46 38.96,44.79 ...

Extracts the first/middle/last frame of every requested B-roll window from the
approved edited A-roll (real ffmpeg extraction), runs real face detection
(OpenCV Haar cascade) on each frame, derives head-shoulder landmarks from the
measured face box, validates through the contract's own validator, and writes
native-inputs/avatar-calibration.json with one avatar contract per window.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))


def sample_frames(arroll: Path, start: float, end: float, folder: Path) -> list[Path]:
    frames = round((end - start) * 24)
    wanted = sorted({0, frames // 2, max(0, frames - 1)})
    paths = []
    for local_frame in wanted:
        ts = start + local_frame / 24
        out = folder / f"f{local_frame:05d}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-ss", f"{ts:.4f}",
                        "-i", str(arroll), "-frames:v", "1", str(out)], check=True)
        paths.append(out)
    return paths


def build_avatar(cv2, validator, arroll: Path, start: float, end: float,
                 source_sha: str, diameter: int = 200):
    total = round((end - start) * 24)
    if end <= start:
        raise SystemExit(f"avatar window must have positive duration: {start},{end}")
    if total < 1:
        raise SystemExit(f"avatar window quantizes to zero frames: {start},{end}")
    wanted = sorted({0, total // 2, max(0, total - 1)})
    cascade = cv2.CascadeClassifier(
        str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    measured = []
    with tempfile.TemporaryDirectory() as td:
        for local_frame in wanted:
            path = Path(td) / f"f{local_frame:05d}.png"
            subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-ss",
                            f"{start + local_frame / 24:.4f}", "-i", str(arroll),
                            "-frames:v", "1", str(path)], check=True)
            image = cv2.imread(str(path))
            gray = cv2.equalizeHist(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
            faces = cascade.detectMultiScale(gray, scaleFactor=1.08,
                                              minNeighbors=6, minSize=(140, 140))
            if len(faces) == 0:
                raise SystemExit(f"no face detected at {path}")
            face = max((tuple(int(v) for v in f) for f in faces), key=lambda f: f[2] * f[3])
            measured.append((local_frame, face))
    # Keep crop size stable from the largest measured face, but derive every
    # landmark's vertical position from the same frame as its face box.
    # Using the largest-face frame's y coordinates for all anchors makes a
    # normal head movement fail the measured head/chin/neck/shoulder order.
    _, _, base_fw, base_fh = max((m[1] for m in measured), key=lambda f: f[2] * f[3])
    crop_size = min(1080, max(int(base_fw * 2.4), int(base_fh * 2.2)))
    anchors = []
    for local_frame, (fx, fy, fw, fh) in measured:
        crop_x = int(min(max(0, fx + fw / 2 - crop_size / 2), 1080 - crop_size))
        crop_y = int(min(max(0, fy - fh * 0.5), 1920 - crop_size))
        anchors.append({
            "frame": local_frame, "x": crop_x, "y": crop_y,
            "landmarks": {
                "head_top": [fx + fw / 2, fy - fh * 0.30],
                "face_box": [float(fx), float(fy), float(fw), float(fh)],
                "chin": [fx + fw / 2, float(fy + fh)],
                "neck": [fx + fw / 2, fy + fh * 1.16],
                "shoulders": [[fx + fw / 2 - base_fw * 0.82, fy + fh * 1.30],
                               [fx + fw / 2 + base_fw * 0.82, fy + fh * 1.30]],
            },
        })
    border = 6
    extent = diameter + border * 2
    return {
        "profile": {"schema_version": 1, "framing": "head-shoulders",
                     "source_sha256": source_sha, "diameter": diameter,
                     "border_width": border, "border_color": "#FFFFFF"},
        "position": {"x": 1080 - extent - 56, "y": 1440},
        "crop": {"size": crop_size, "anchors": anchors},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-context", type=Path, required=True)
    parser.add_argument("--windows", nargs="+", required=True)
    args = parser.parse_args()
    import cv2

    job_dir = Path(json.loads(args.job_context.read_text())["job_dir"])
    arroll = job_dir / "06-edit-structure/edited-aroll.mp4"
    source_sha = hashlib.sha256(arroll.read_bytes()).hexdigest()

    from importlib import util as importlib_util
    spec = importlib_util.spec_from_file_location(
        "avatar_profile", SKILL / "scripts/avatar_profile.py")
    validator = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    result = {}
    for window in args.windows:
        start, end = (float(x) for x in window.split(","))
        if end <= start:
            raise SystemExit(f"invalid avatar window: {window}")
        if round((end - start) * 24) < 1:
            raise SystemExit(f"avatar window quantizes to zero frames: {window}")
        avatar = build_avatar(cv2, validator, arroll, start, end, source_sha)
        validator.validate_avatar(avatar, frames=round((end - start) * 24))
        result[f"{start:.3f},{end:.3f}"] = avatar
    out = job_dir / "native-inputs/avatar-calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"windows": len(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

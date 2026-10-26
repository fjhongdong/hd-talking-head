#!/usr/bin/env python3
"""Calibrate bottom-window avatars for B-roll segments from the edited A-roll.

Usage:
  python3 calibrate_avatars.py --job-context ctx --windows 24.04,32.46 38.96,44.79 ...

Extracts the first/middle/last frame of every requested B-roll window from the
approved edited A-roll (real ffmpeg extraction) and runs real face detection
(OpenCV Haar cascade). Detection is only a candidate reference: formal avatar
landmarks must be measured by a person in the existing calibration contract.
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


def build_avatar(cv2, arroll: Path, start: float, end: float,
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
    # Keep this as an explicitly non-authoritative suggestion. In particular,
    # do not turn face proportions into head/neck/shoulder measurements.
    _, _, base_fw, base_fh = max((m[1] for m in measured), key=lambda f: f[2] * f[3])
    crop_size = min(1080, max(int(base_fw * 2.4), int(base_fh * 2.2)))
    frames = []
    for local_frame, (fx, fy, fw, fh) in measured:
        crop_x = int(min(max(0, fx + fw / 2 - crop_size / 2), 1080 - crop_size))
        crop_y = int(min(max(0, fy - fh * 0.5), 1920 - crop_size))
        frames.append({
            "frame": local_frame,
            "face_box": [float(fx), float(fy), float(fw), float(fh)],
            "crop_suggestion": {"x": crop_x, "y": crop_y, "size": crop_size},
        })
    return {
        "source_sha256": source_sha,
        "window": {"start": start, "end": end, "frames": total},
        "frames": frames,
        "manual_required": True,
        "manual_required_reason": (
            "Face detection is a candidate reference only; measure and enter "
            "head_top, chin, neck, and both shoulders in avatar-calibration.json."
        ),
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

    result = {}
    for window in args.windows:
        start, end = (float(x) for x in window.split(","))
        if end <= start:
            raise SystemExit(f"invalid avatar window: {window}")
        if round((end - start) * 24) < 1:
            raise SystemExit(f"avatar window quantizes to zero frames: {window}")
        avatar = build_avatar(cv2, arroll, start, end, source_sha)
        result[f"{start:.3f},{end:.3f}"] = avatar
    out = job_dir / "native-inputs/avatar-calibration-candidates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"windows": len(result), "manual_required": True,
                      "candidate_path": str(out)}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

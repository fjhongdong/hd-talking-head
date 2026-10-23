#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

def run(command):
    subprocess.run(command, check=True)

parser = argparse.ArgumentParser()
parser.add_argument("video")
parser.add_argument("--reference")
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()

video = Path(args.video).resolve()
out = Path(args.output_dir).resolve()
out.mkdir(parents=True, exist_ok=True)
probe = subprocess.run([
    "ffprobe", "-v", "error", "-show_entries",
    "format=duration:stream=index,codec_type,width,height,r_frame_rate",
    "-of", "json", str(video)
], check=True, capture_output=True, text=True)
metadata = json.loads(probe.stdout)
(out / "probe.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
duration = float(metadata["format"]["duration"])
run(["ffmpeg", "-y", "-i", str(video), "-vf", "fps=2,scale=270:-1,tile=4x3", "-frames:v", "1", "-update", "1", str(out / "contact-sheet.jpg")])
run(["ffmpeg", "-y", "-ss", f"{max(0.0, duration - 0.12):.3f}", "-i", str(video), "-frames:v", "1", "-update", "1", str(out / "last-frame.png")])
if args.reference:
    run(["ffmpeg", "-y", "-i", str(Path(args.reference).resolve()), "-i", str(out / "last-frame.png"), "-filter_complex", "[0:v]scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2:white[a];[1:v]scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2:white[b];[a][b]hstack=inputs=2", "-frames:v", "1", "-update", "1", str(out / "end-frame-comparison.jpg")])
print(out)

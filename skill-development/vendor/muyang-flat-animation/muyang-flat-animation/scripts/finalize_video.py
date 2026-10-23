#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description="Resize a generated video and keep or strip its audio.")
parser.add_argument("input")
parser.add_argument("output")
parser.add_argument("--width", type=int, required=True)
parser.add_argument("--height", type=int, required=True)
parser.add_argument("--fps", type=int, default=24)
parser.add_argument("--fit", choices=("crop", "pad"), default="crop")
parser.add_argument("--background", default="0xEEE9DB")
parser.add_argument("--audio", choices=("keep", "strip"), default="keep")
args = parser.parse_args()

if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
    raise SystemExit("Width and height must be positive even integers.")

source = Path(args.input).resolve()
target = Path(args.output).resolve()
target.parent.mkdir(parents=True, exist_ok=True)

if args.fit == "crop":
    vf = (
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
        f"crop={args.width}:{args.height},fps={args.fps}"
    )
else:
    vf = (
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,"
        f"pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:color={args.background},fps={args.fps}"
    )

command = [
    "ffmpeg", "-y", "-i", str(source), "-map", "0:v:0", "-vf", vf,
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart"
]
if args.audio == "keep":
    command.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"])
else:
    command.append("-an")
command.append(str(target))
subprocess.run(command, check=True)
print(target)

#!/bin/sh
# raw/ → assets/: match footage as frames (1280×720 → 1920×1080, 1.5×, the upper limit for modern footage), photos, original sound
#   a/  Commons clip (third goal, 14 s, 350 frames) — all tracking keyframes for the third goal use these frame numbers
#   b/  official highlights, 196 frames from 110.52 s: 55′ first goal, main camera
#   c/  official highlights, 192 frames from 140.80 s: 61′ second goal, main camera (F001–F090) + high reverse-angle replay (F091–F192)
set -e
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"
LIB=${LIB:-$(cd "$D/../../.." && pwd)}; PY="$LIB/.venv/bin/python"
A=assets; mkdir -p $A/a $A/b $A/c audio
# deblock → lanczos 1.5× → light sharpen; one light grade for all (a little less saturation, highlights pulled down, cooler shadows); grain is added once, in the mux
VF="hqdn3d=1.2:1.2:2.5:2.5,scale=1920:1080:flags=lanczos,unsharp=5:5:0.55:5:5:0,eq=saturation=0.9:contrast=1.04:gamma=0.97,colorbalance=bs=0.03:bm=0.0:rh=-0.01"
[ -s $A/a/350.jpg ] || ffmpeg -v error -y -i raw/kald.webm -an -vf "$VF" -q:v 3 -start_number 1 $A/a/%03d.jpg
[ -s $A/b/196.jpg ] || ffmpeg -v error -y -ss 110.52 -i raw/yt/summary.mp4 -t 7.84 -an -vf "$VF" -q:v 3 -start_number 1 $A/b/%03d.jpg
[ -s $A/c/192.jpg ] || ffmpeg -v error -y -ss 140.80 -i raw/yt/summary.mp4 -t 7.68 -an -vf "$VF" -q:v 3 -start_number 1 $A/c/%03d.jpg
# photos: the stadium exterior cropped to 16:9 at 1920×1080 (original 1920×1440, crop only, no upscaling); portraits keep their original size
"$PY" -I -c "
from PIL import Image
im=Image.open('raw/stadium.jpg').convert('RGB'); w,h=im.size; t=int((h-w*9/16)*0.45)
im.crop((0,t,w,t+int(w*9/16))).resize((1920,1080),Image.LANCZOS).save('$A/stadium.jpg',quality=90)
Image.open('raw/hak.jpg').convert('RGB').save('$A/hak.jpg',quality=92)
"
# original sound, 48 kHz stereo: the Commons clip + the official highlights (taking the original sound of the first two goals)
ffmpeg -v error -y -i raw/kald.webm -vn -ac 2 -ar 48000 audio/orig.wav
ffmpeg -v error -y -ss 108 -i raw/yt/summary.mp4 -t 45 -vn -ac 2 -ar 48000 audio/orig2.wav   # highlights 108–153 s
ls $A/a $A/b $A/c | wc -l

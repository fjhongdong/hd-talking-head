#!/bin/sh
# raw/ → frames/<cam>/NNNN.jpg: 30 fps frame sequences named by "film frame number" (with a unified grade), plus the photo / document.
# Film time t ↔ mission time M = t − 32.5 (T0 at t = 32.5). All sync relationships are fixed here (see the "sync table" in STYLE.md):
#   cam      source s = …        film range (only what's used)   how it was synced
#   live     s = M + 46.8        t 0 – 59.5                 the broadcast bug's T−0:00:32→31 tick + the commentary word by word ("booster" 47.0)
#   slscam   s = M + 34.8        t 17 – 59.5                the mission timer burned into the footage 002-00:00:00.000 (frame-accurate)
#   orion    s = M + 26.25       t 22 – 33                  first light of RS-25 startup (T−6.36) at source 19.9 s
#   uas      s = M + 10.4        t 23 – 59.5                ignition flash (measured)
#   banana   s = M + 19.0        t 26 – 43                  brightness jump at booster ignition (source 19.0–19.1 s)
#   osb      s = 3.0 + 2.5·M     t 32 – 37 (2.5× slow motion restored to real time)  RS-25 white vapour → booster grey smoke 15 s ≈ real 6.36 s
#   fr1      not synced (no clock): t 2.5–13.2 ← s = t + 19.9; t 25.2 – 32.8 ← s = t + 10.8 (shots from the same stretch of the countdown)
set -e
cd "$(dirname "$0")/.."
F=frames; rm -rf $F; mkdir -p $F
G="eq=contrast=1.07:saturation=0.9:gamma=0.97:brightness=-0.01,colorbalance=rs=-0.02:bs=0.03:rh=0.03:bh=-0.02"
X="-v error -y"
# cut <cam> <source start> <film start> <duration> <filter>
cut() {
  mkdir -p $F/$1
  n=$(python3 -c "print(round($3*30))")
  ffmpeg $X -ss $2 -t $4 -i raw/$6.mp4 -vf "fps=30,$5,$G" -q:v 3 -start_number $n $F/$1/%04d.jpg
}
# live broadcast 4K → 1920
cut live 14.3 0 59.6 "scale=1920:1080:flags=lanczos" live4k
# the push-in on the sound-suppression-water line (t 16.4–24.5): a second set from the same broadcast source at 2880 wide, so a 1.5× push-in is still native source pixels (no upscaling)
cut livehi 30.7 16.4 8.2 "scale=2880:1620:flags=lanczos" live4k
# onboard rocket camera 720p: first blank out the timer at top-left (used only for syncing), then scale up as needed (at most 1.5× full-screen)
cut slscam 19.3 17 42.6 "delogo=x=12:y=20:w=188:h=54,scale=1920:1080:flags=lanczos,unsharp=5:5:0.35" slscam
# Orion downward-looking camera: rotate 90° clockwise so the vehicle is at the top and the ground at the bottom
cut orion 15.75 22 11 "crop=760:1080:960:0,transpose=1" orioncam
# drone 1920×1012
cut uas 0.9 23 36.6 "scale=2049:1080:flags=lanczos,crop=1920:1080,unsharp=5:5:0.3" uas
# Banana Creek long shot
cut banana 12.5 26 17 "null" banana
# OSB slow motion: 2.5× slow → setpts/2.5 restores real time (film t 32 onward = M −0.5 = source 1.75)
mkdir -p $F/osb
ffmpeg $X -ss 1.75 -t 13 -i raw/osb.mp4 -vf "setpts=(PTS-STARTPTS)/2.5,fps=30,scale=1920:1080:flags=lanczos,$G" -q:v 3 -start_number 960 $F/osb/%04d.jpg
# firing room (same window, not frame-synced)
cut fr1 22.4 2.5 10.7 "null" fr1
cut fr1 36.0 25.2 7.6 "null" fr1
# photo + document
ffmpeg $X -i raw/walkout_0004.jpg -vf "crop=4900:3100:420:1100,scale=1960:-2:flags=lanczos,$G" -q:v 2 $F/photo.jpg
ffmpeg $X -i raw/onepager.jpg -q:v 2 -vf "scale=2880:-2:flags=lanczos" $F/doc.jpg
for d in $F/*/; do echo "$d $(ls $d | head -1) … $(ls $d | tail -1) ($(ls $d | wc -l | tr -d ' '))"; done

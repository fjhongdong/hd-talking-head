#!/bin/sh
# raw/ → assets/: footage frames, document pages, photos, map and source-audio clips used by the page.
# Old film: deinterlace → crop black borders → deblock → lanczos upscale 1.6× → light sharpening → greyscale (the unified grade is done in the page).
set -e
D=$(cd "$(dirname "$0")/.." && pwd); cd "$D"
LIB=${LIB:-$(cd "$D/../../.." && pwd)}; PY="$LIB/.venv/bin/python"
A=assets; mkdir -p $A/app $A/fire $A/nyc $A/snd
VF="bwdif=0,scale=640:480,setsar=1,crop=600:450:22:14,hqdn3d=2:2:3:3,scale=960:720:flags=lanczos,unsharp=5:5:0.5:5:5:0,format=gray"
ff() { ffmpeg -v error -y "$@"; }
# Aerial over New York src 38.0–41.6 s (background for the title package, 30 fps)
ff -ss 38.0 -t 3.6 -i raw/univ.mpeg -an -vf "$VF,fps=30" -q:v 3 $A/nyc/%03d.jpg
# Approach footage src 59.4–67.1 s (30 fps)
ff -ss 59.4 -t 7.7 -i raw/univ.mpeg -an -vf "$VF,fps=30" -q:v 3 $A/app/%03d.jpg
# Continuous fire footage src 78.6–104.4 s (10 fps, swept through at about 7× in the film; the cold-open rewind uses it too)
ff -ss 78.6 -t 25.8 -i raw/univ.mpeg -an -vf "$VF,fps=10" -q:v 3 $A/fire/%03d.jpg
# Freeze frames: ignition (src 80.2, fireball at the top edge of the hull), ground impact (src 103.6), wreckage (src 165.0)
ff -ss 80.2 -i raw/univ.mpeg -an -frames:v 1 -vf "$VF" -q:v 2 $A/freeze_fire.jpg
ff -ss 103.6 -i raw/univ.mpeg -an -frames:v 1 -vf "$VF" -q:v 2 $A/freeze_impact.jpg
ff -ss 165.0 -i raw/univ.mpeg -an -frames:v 1 -vf "$VF" -q:v 2 $A/wreck.jpg
# Source-audio clips (newsreel commentary): C1 src 78.10–81.56 "a roar and a burst of flame near the big tail fins"
#                         C2 src 40.38–44.72 "taking the lives of almost half its 99 passengers and crew"
ff -ss 78.10 -t 3.46 -i raw/univ.mpeg -vn -ac 1 -ar 48000 $A/snd/c1.wav
ff -ss 40.38 -t 4.34 -i raw/univ.mpeg -vn -ac 1 -ar 48000 $A/snd/c2.wav
# FBI file pages (200 dpi, greyscale): p13 teletype 1937-05-08, p20 teletype 1937-05-09, p39 Tyler testimony
for p in 13 20 39; do pdftoppm -f $p -l $p -r 200 -gray -png raw/fbi01.pdf $A/fbi; mv $A/fbi-0$p.png $A/fbi_p$p.png; done
# USGS 1947 quadrangle: the air-station area, 300 dpi (1 px ≈ 6.67 ft)
pdftoppm -r 300 -x 2000 -y 4600 -W 2400 -H 1500 -png -singlefile raw/usgs1947.pdf $A/usgs_raw
# Photos: downscale to ≤2400 (downscale only, never up); the map is converted to greyscale and inverted into thin lines on a dark ground
"$PY" -I -c "
from PIL import Image, ImageOps, ImageEnhance
for s,o in [('raw/pasq.jpg','$A/pasq.jpg'),('raw/nh57973.png','$A/nh.jpg'),('raw/nara518856.jpg','$A/nara.jpg')]:
    im=Image.open(s).convert('L'); im.thumbnail((2400,2400),Image.LANCZOS); im.save(o,quality=90)
m=Image.open('$A/usgs_raw.png').convert('L'); m=ImageOps.autocontrast(m,cutoff=1); m=ImageOps.invert(m)
m=ImageEnhance.Contrast(m).enhance(1.15); m.save('$A/usgs.jpg',quality=90)
"
rm -f $A/usgs_raw.png
echo "nyc $(ls $A/nyc | wc -l) app $(ls $A/app | wc -l) fire $(ls $A/fire | wc -l)"

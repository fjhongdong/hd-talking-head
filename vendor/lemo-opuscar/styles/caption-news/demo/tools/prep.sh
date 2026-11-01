#!/bin/sh
# Prepare every picture the page draws: video shots as 30 fps JPEG sequences at their final display size
# (lanczos up-scale within the limits: modern footage <= 1.5x, then a light unsharp), report pages, photos.
# Run from anywhere: sh tools/prep.sh
set -e
H=$(cd "$(dirname "$0")/.." && pwd); cd "$H"
mkdir -p assets/fr assets/img
SH="unsharp=5:5:0.45:5:5:0"
# seg <name> <src> <start s> <dur s> <crop w:h:x:y> <out w> <out h> [extra filters]
seg() {
  rm -f assets/fr/$1_*.jpg
  vf="fps=30,crop=$5,scale=$6:$7:flags=lanczos,$SH${8:+,$8}"
  ffmpeg -v error -y -ss "$3" -t "$4" -i "raw/$2" -an -vf "$vf" -q:v 3 "assets/fr/$1_%03d.jpg"
  echo "$1 $(ls assets/fr/$1_*.jpg | wc -l | tr -d ' ') frames  ($2 @ $3 s, crop $5 -> $6x$7)"
}
# Altena TV footage: the station logo sits at x 1550-1770, y 75-165, so every crop stays left of x 1536.
# Two hive stencils (a beekeeper's name and phone number) are blurred with delogo.
seg h1  v_rows.webm     28.0 1.6 1536:864:0:180   1920 1080                       # 1.25x  wide rows of hives
seg h2  v_apiary.webm   88.0 1.6 1280:720:0:0     1920 1080                       # 1.50x  bees landing (USDA)
seg h3  v_slow40.webm    7.0 2.1 1440:810:0:135   1920 1080                       # 1.33x  slow-motion flight
seg st  v_entrance.mp4   1.0 2.7 704:720:440:0    1056 1080                       # 1.50x  hive entrance (sting panel)
seg hf  v_rows.webm     14.6 3.1 1536:864:0:120   1920 1080 "delogo=x=28:y=478:w=112:h=136,delogo=x=982:y=538:w=88:h=130,delogo=x=982:y=780:w=88:h=112"  # 1.25x  close rows (half)
seg fz  v_flight.webm   92.0 1.4 1920:1080:0:0    1920 1080                       # 1.00x  flight -> freeze
seg sl  v_rows.webm     14.6 4.6 864:972:440:108  960 1080 "delogo=x=389:y=497:w=67:h=106,delogo=x=389:y=713:w=67:h=89"  # 1.11x  split: the dead column
seg sr  v_apiary.webm  156.5 4.6 640:720:320:0    960 1080                        # 1.50x  split: the living column (bees on comb)
seg g1  v_apiary.webm  124.0 4.1 432:720:600:0    648 1080                        # 1.50x  grid: working the frames
seg rb  v_apiary.webm  104.0 3.6 1280:720:0:0     1920 1080                       # 1.50x  rooftop apiary
seg vd  v_flight.webm   14.0 4.1 1920:1080:0:0    1920 1080                       # 1.00x  verdict
seg ed  v_entrance.mp4 20.0 5.1 1280:720:0:0      1920 1080                       # 1.50x  end card background (blurred in page)
# report pages at 220 dpi (1 pt = 3.0556 px)
[ -s raw/report/page-01.png ] || pdftoppm -r 220 -f 1 -l 1 -png raw/doc_nass.pdf raw/report/page
ffmpeg -v error -y -i raw/report/page-01.png -q:v 2 assets/img/doc1.jpg
# photos: scaled to the largest size they are shown at (never above 1:1)
ffmpeg -v error -y -i raw/p_sem.jpg     -q:v 2 assets/img/sem.jpg
ffmpeg -v error -y -i raw/p_almond.jpg  -q:v 2 assets/img/almond.jpg
ffmpeg -v error -y -i raw/p_package.jpg -vf "scale=1368:-2:flags=lanczos" -q:v 2 assets/img/package.jpg
ffmpeg -v error -y -i raw/p_queen.jpg   -q:v 2 assets/img/queen.jpg
# map: US states (Natural Earth 1:110m, public domain) projected to Albers USA-like coordinates
python3 tools/map_prep.py raw/geo/geo_states.geojson assets/states.json
echo "prep done"

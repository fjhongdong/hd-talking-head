#!/bin/sh
# Download every source the film uses into raw/ (skips what is already there). Licences and pages are logged
# by footage.py into SOURCES.jsonl. Wikimedia rate-limits bursts (HTTP 429): files are fetched one at a time
# with pauses; run again if one fails.
set -e
H=$(cd "$(dirname "$0")/.." && pwd); cd "$H"; PY=${PY:-python3}
f() { [ -s "raw/$2" ] && return 0; python3 tools/footage.py fetch "$1" --name "${2%.*}" ${3:+--max-mb $3}; sleep 4; }
f 'commons:File:Te veel bijen in de Biesbosch door bijenkasten in de Noordwaard - Altena TV.webm' v_rows.webm
f "commons:File:People's Garden Apiary and Pollinator Garden (20130522-NRCS-LSC-0226-v6).webm" v_apiary.webm
f 'commons:File:Apis mellifera flying x40 SlowMotion01.webm' v_slow40.webm
f 'commons:File:Slow Motion Bee Flight - Close-up video of honey bees.webm' v_flight.webm
f 'commons:File:Рій на землі 02.webm' v_swarm.webm 400
f 'commons:File:Three bee packages for Park (16272512611).jpg' p_package.jpg
f 'commons:File:Varroa destructor on honeybee host.jpg' p_sem.jpg
f 'commons:File:20140225-OC-DK-0002 (12813166013).jpg' p_almond.jpg
# the 19-minute "Bees flying in HD in slow motion" (202 MB): only a 40 s segment from 400 s
[ -s raw/v_entrance.mp4 ] || "$PY" tools/commons-tools/seg.py "File:Bees flying in HD in slow motion.webm" v_entrance 400 40 "CC BY 3.0" "Midsummer Bees"
# queen photo: the 1920 px Commons thumbnail (the original is 3000 px; the film shows it at 0.9)
[ -s raw/p_queen.jpg ] || "$PY" tools/commons_thumb.py "File:Queen Bee (16545241268).jpg" p_queen 1920
[ -s raw/doc_nass.pdf ] || curl -fsSL -o raw/doc_nass.pdf https://release.nass.usda.gov/reports/hcny0726.pdf
mkdir -p raw/geo; [ -s raw/geo/geo_states.geojson ] || curl -fsSL -o raw/geo/geo_states.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_1_states_provinces.geojson
# natural sound: the swarm video's own audio, first 40 s, mono 48 kHz
mkdir -p audio/src; [ -s audio/src/swarm.wav ] || ffmpeg -v error -y -i raw/v_swarm.webm -t 40 -vn -ac 1 -ar 48000 audio/src/swarm.wav
echo "sources ready"

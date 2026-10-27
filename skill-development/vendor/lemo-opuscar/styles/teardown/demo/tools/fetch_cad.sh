#!/bin/sh
# Regenerate data/pcb.json and data/case.bin from the open-source repo foostan/crkbd (pinned commit 63366fb).
# Needs: network, python3, node, npm (installs occt-import-js@0.0.23 temporarily into $TMP)
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
TMP=${TMP_DIR:-$(mktemp -d)}
REV=63366fb7f51cf2a796462fdd90527e99dd126055
B=https://raw.githubusercontent.com/foostan/crkbd/$REV
mkdir -p "$TMP/dl" "$TMP/occt"
for f in pcbs/corne-cherry/hotswap/corne-cherry.kicad_pcb plates/3x6/pcb/plate-top-cherrymx.kicad_pcb cases/3x6/left.step; do
  curl -sfL -o "$TMP/dl/$(basename "$f")" "$B/$f"
done
python3 -I "$HERE/tools/extract_pcb.py" "$TMP/dl/corne-cherry.kicad_pcb" "$TMP/dl/plate-top-cherrymx.kicad_pcb" "$HERE/data/pcb.json"
(cd "$TMP/occt" && npm init -y >/dev/null && npm i --silent occt-import-js@0.0.23)
OCCT_DIR="$TMP/occt" node "$HERE/tools/step2mesh.mjs" "$TMP/dl/left.step" "$HERE/data/case.bin"
echo "data regenerated from crkbd@$REV"

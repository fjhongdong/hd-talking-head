#!/bin/sh
# Two illustrative plates for this demo (server aisle, silicon wafer). Optional: the finished JPEGs are committed in assets/plates/.
# With the Codex CLI: tools/gen_image.py generates each one (results differ every run), then it is saved as assets/plates/<name>.jpg.
# With another image tool: use the same prompts, export 16:9 (≥ 1600 px wide) and save to assets/plates/<name>.jpg.
# On-screen words are always typeset in code; the plates are tagged "ILLUSTRATION / 示意" ("illustration") whenever visible.
set -e
cd "$(dirname "$0")/.."
LIB=${LIB:-$(cd ../../.. && pwd)}
PY="$LIB/.venv/bin/python"
COMMON="Photorealistic editorial news b-roll still, 16:9, cinematic, natural light, shallow depth of field. Absolutely no text, no letters, no numbers, no logos, no brand marks, no flags, no people, no faces."
gen() { out=$(python3 tools/gen_image.py "$2 $COMMON" --aspect 16:9 --out gen --name "$1" --timeout 420)
  "$PY" -c "import sys; from PIL import Image; Image.open(sys.argv[1]).convert('RGB').save(sys.argv[2], quality=88, optimize=True)" "$out" "assets/plates/$1.jpg"
  echo "assets/plates/$1.jpg"; }
mkdir -p gen assets/plates
gen plate_datacenter "Long aisle of a dim modern data center, rows of black server racks with tiny white and amber status lights, cool haze, symmetrical one-point perspective, camera at chest height."
gen plate_wafer "Macro close-up of a polished silicon wafer covered in a grid of microchip dies, iridescent reflections, held in a dark cleanroom, low-key lighting, diagonal composition."

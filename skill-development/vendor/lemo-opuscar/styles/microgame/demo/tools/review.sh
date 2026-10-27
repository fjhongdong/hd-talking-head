#!/bin/bash
# Contact sheet of sampled frames: bash tools/review.sh <outdir> <cols> t1 t2 ...  → <outdir>/sheet.jpg (paths are handled automatically when run from the repo root)
cd "$(dirname "$0")/../../../.."
D=styles/microgame/demo; OUT=$1; COLS=$2; shift 2
node core/render/still.mjs $D "$@" --out $D/$OUT --prefix k_ >/dev/null || exit 1
FILES=(); for t in "$@"; do FILES+=("$D/$OUT/k_$t.jpg"); done
.venv/bin/python core/render/sheet.py $D/$OUT/sheet.jpg "${FILES[@]}" --cols $COLS --w $((1920 / COLS))

#!/bin/bash
# grab stills to check the cut: sh tools/stills.sh sec sec … → work/st/t_<sec>.jpg + work/st_sheet.jpg
cd "$(dirname "$0")/.."
PY=../../../.venv/bin/python
mkdir -p work/st; A=(); F=()
for t in "$@"; do A+=("$t" "work/st/t_$t.jpg"); F+=("work/st/t_$t.jpg"); done
$PY tools/render.py --still "${A[@]}" | tail -1
$PY ../../../core/render/sheet.py work/st_sheet.jpg "${F[@]}" --cols 4 --w 480

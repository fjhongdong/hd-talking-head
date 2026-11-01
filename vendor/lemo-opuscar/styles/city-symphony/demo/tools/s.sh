#!/bin/sh
# serial search, back off and retry on 429:sh tools/s.sh "<query>" [type] [n]
for k in 1 2 3 4 5; do
  out=$(python3 tools/footage.py search commons "$1" --type "${2:-video}" -n "${3:-25}" 2>&1)
  case "$out" in *"HTTP Error 429"*|*"Traceback"*) echo "retry $k" >&2; sleep $((20*k));; *) echo "$out"; exit 0;; esac
done
echo "$out" | tail -2

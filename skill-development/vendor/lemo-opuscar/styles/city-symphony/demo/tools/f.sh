#!/bin/sh
# footage.py fetch with 429 back-off: sh tools/f.sh <src> <name> [other args…]
src="$1"; name="$2"; shift 2
for k in 1 2 3 4 5 6; do
  if python3 tools/footage.py fetch "$src" --name "$name" --out raw --max-mb 400 "$@" > /dev/null 2> work/fetch_err.txt; then
    python3 tools/footage.py fetch "$src" --name "$name" --out raw --max-mb 400 "$@" 2>/dev/null | tail -1; exit 0; fi
  tail -1 work/fetch_err.txt; rm -f "raw/$name".*; sleep $((25*k))
done
exit 1

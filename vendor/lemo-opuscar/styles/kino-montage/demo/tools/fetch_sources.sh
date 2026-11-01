#!/bin/sh
# Download every source the film uses into raw/ (URLs and licences: SOURCES.jsonl / SOURCES.md).
# Serial and patient: Wikimedia Commons rate-limits shared IPs (HTTP 429) and serves the photos as
# standard-width thumbnails (1920 px); the Internet Archive files are the originals.
cd "$(dirname "$0")/.." && mkdir -p raw
UA="LemoOpuscar/1.0 (film style library; footage for a public-domain demo)"
python3 - <<'PY' | while read -r f u; do
import json
for l in open('SOURCES.jsonl'):
    x = json.loads(l); print(x['file'], x['url'])
PY
  [ -s "$f" ] && { echo "have $f"; continue; }
  for k in 1 2 3 4 5; do curl -sfL -A "$UA" -m 600 -o "$f" "$u" && break; echo "retry $f"; sleep $((k * 15)); done
  [ -s "$f" ] && echo "got $f" || { echo "failed $f"; exit 1; }
  sleep 3
done

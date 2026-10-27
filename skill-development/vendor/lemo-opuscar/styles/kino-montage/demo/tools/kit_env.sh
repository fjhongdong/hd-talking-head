#!/bin/sh
# Print a python that can run tools/prep.py (numpy, pillow, scipy, onnxruntime) and make sure the
# u2net_human_seg model is in ~/.rembg/models. Uses the library venv when it already has onnxruntime,
# otherwise builds a private demo/.venv (never installs into the library venv).
HERE=$(cd "$(dirname "$0")/.." && pwd)
LIBPY="${LIB:-$(cd "$HERE/../../.." && pwd)}/.venv/bin/python"
M="$HOME/.rembg/models/u2net_human_seg/u2net_human_seg.onnx"
if [ ! -f "$M" ]; then
  mkdir -p "$(dirname "$M")"
  curl -sfL -m 900 -o "$M" https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx >&2 || { echo "model download failed" >&2; exit 1; }
fi
if "$LIBPY" -c "import onnxruntime, scipy, PIL" 2>/dev/null; then echo "$LIBPY"; exit 0; fi
if [ ! -x "$HERE/.venv/bin/python" ]; then
  python3 -m venv "$HERE/.venv" >&2 && "$HERE/.venv/bin/pip" -q install numpy pillow scipy onnxruntime >&2
fi
echo "$HERE/.venv/bin/python"

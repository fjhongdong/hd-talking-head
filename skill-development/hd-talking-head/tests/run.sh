#!/bin/sh
# Run the skill's unittest suite from any working directory.
# Usage: tests/run.sh            -> discover and run every test module
#        tests/run.sh test_x ... -> run only the named modules
#
# Interpreter preference: the project runtime python (created by
# project_python.py --prepare, carries Pillow/NumPy/OpenCV), else the newest
# python >= 3.10 on PATH (the project runtime uses zip(strict=True) syntax).
# Pillow-dependent tests skip cleanly on interpreters without it.
set -e
SKILL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROJECT=$(CDPATH= cd -- "$SKILL_ROOT/../.." && pwd)
cd "$SKILL_ROOT"

PYTHON=""
for candidate in "$PROJECT"/skill-development/runtime/talking-head-python*/bin/python3; do
    if [ -x "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done
# 统一依赖目录内的二进制扩展按解释器版本编译:优先选与目录配对的解释器(312 目录配 3.12)。
if [ -z "$PYTHON" ]; then
    for pkgdir in "$PROJECT"/skill-development/runtime/talking-head-python*; do
        [ -d "$pkgdir/PIL" ] || continue
        ver=$(basename "$pkgdir"); ver=${ver#talking-head-python}
        candidate="python${ver:0:1}.${ver:1}"
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON="$candidate"
            EXTRA_PATH="$pkgdir"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
            PYTHON="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "error: no python >= 3.10 found on PATH" >&2
    exit 2
fi

# 统一依赖目录:项目运行时包目录(PIL/NumPy/OpenCV 等)由 prepare 维护。
EXTRA_PATH=""
for pkgdir in "$PROJECT"/skill-development/runtime/talking-head-python*; do
    if [ -d "$pkgdir/PIL" ]; then
        EXTRA_PATH="$pkgdir"
        break
    fi
done

if [ "$#" -gt 0 ]; then
    PYTHONPATH="$PROJECT:$EXTRA_PATH:$SKILL_ROOT/tests" exec "$PYTHON" -m unittest "$@"
else
    PYTHONPATH="$PROJECT:$EXTRA_PATH" exec "$PYTHON" -m unittest discover -s tests -p "test_*.py" -v
fi

"""Shared test environment bootstrap: canonical paths and runtime probes.

New tests import this module first instead of re-deriving SKILL/PROJECT or
crashing on missing runtimes. It never raises on a bare checkout; tests opt
into skipping with EDIT_HD_AVAILABLE.
"""

from __future__ import annotations

import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
if str(SKILL / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL / "scripts"))

try:
    import edit.hd  # noqa: F401
    EDIT_HD_AVAILABLE = True
except ImportError:
    EDIT_HD_AVAILABLE = False

# edit.hd 导入期会清洗 sys.path(防宿主路径污染),统一依赖目录随之被摘。
# 在项目路径之后恢复,供 Pillow/NumPy 等在测试进程内导入;append 到末尾
# 不改变项目路径的解析优先次序。
for _candidate in sorted((SKILL.parent / "runtime").glob("talking-head-python*")):
    if (_candidate / "PIL").is_dir():
        sys.path.append(str(_candidate))
        break

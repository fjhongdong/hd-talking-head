"""Cross-package surface guard: every skill file referenced by edit/hd must exist.

The runtime (edit/hd/tools) references skill files by path (the assembled
native-clock checker, adapters, registries...). Those references are invisible
to skill-internal cross-checks, which is how a runtime dependency was once
deleted as an "orphan". This test scans the runtime's string literals for
skill paths and fails when any referenced file is missing from the package.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import _env  # noqa: F401


SKILL = _env.SKILL
RUNTIME_TOOLS = _env.PROJECT / "edit/hd/tools"
PATTERN = re.compile(
    r"(?:skill-development/hd-talking-head/)"
    r"((?:scripts|references|assets)/[A-Za-z0-9_./\\-]+\.(?:py|mjs|cjs|md|json))"
    r"|(?<![\w/])((?:scripts)/[A-Za-z0-9_.\-]+\.(?:py|mjs|cjs))"
)


def referenced_skill_files() -> set[str]:
    found: set[str] = set()
    for source in sorted(RUNTIME_TOOLS.glob("*.py")):
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in PATTERN.finditer(text):
            relative = match.group(1) or match.group(2)
            found.add(relative)
    return found


class CrossPackageSurfaceTests(unittest.TestCase):
    def test_every_runtime_referenced_skill_file_exists(self):
        references = referenced_skill_files()
        self.assertGreaterEqual(len(references), 3, "runtime reference scan found nothing; update the pattern")
        missing = sorted(
            relative for relative in references
            if not (SKILL / relative).is_file()
        )
        self.assertEqual(missing, [],
                         "edit/hd 运行时引用了包内不存在的文件(防误删守卫):\n  " + "\n  ".join(missing))

    def test_clock_checker_is_covered(self):
        references = referenced_skill_files()
        self.assertIn("scripts/check_native_overlay_clock.mjs", references)


if __name__ == "__main__":
    unittest.main()

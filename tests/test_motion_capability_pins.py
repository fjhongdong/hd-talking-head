"""Cross-package guard: the pinned capability index must match skill sources on disk."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

try:
    from edit.hd.tools import motion_capabilities
except ImportError:
    motion_capabilities = None


@unittest.skipUnless(motion_capabilities is not None, "edit.hd runtime is unavailable")
class MotionCapabilityPinTests(unittest.TestCase):
    def test_pinned_capability_sources_match_disk(self):
        profiles = motion_capabilities.load_profiles(PROJECT)
        self.assertGreaterEqual(len(profiles), 150)
        for candidate_id in (
            "adu-motion-video:adu-motion-video/native-compare",
            "hypit-native-chat:hypit/native-plan-change-chat",
            "wise-motion:wise-motion/orbit-tracking-component",
        ):
            self.assertIn(candidate_id, profiles)


if __name__ == "__main__":
    unittest.main()

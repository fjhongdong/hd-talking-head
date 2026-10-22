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

    def test_unconnected_and_historical_candidates_are_refused(self):
        profiles = motion_capabilities.load_profiles(PROJECT)
        unconnected = next(cid for cid in profiles if cid.startswith("unconnected:"))
        historical = next(cid for cid in profiles if cid.startswith("history:"))
        for cid in (unconnected, historical):
            profile = profiles[cid]
            candidate = {"candidate_id": cid, "role": "broll",
                         "producer_version": profile["reviewed_version"]}
            with self.assertRaisesRegex(ValueError, "not reviewed"):
                motion_capabilities.describe_candidates(PROJECT, [candidate], use="broll")


if __name__ == "__main__":
    unittest.main()

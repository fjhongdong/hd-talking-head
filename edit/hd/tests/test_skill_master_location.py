"""The project runtime loads the Skill under local development."""

from pathlib import Path
import unittest

from edit.hd.tools import visual_plan


class SkillMasterLocationTests(unittest.TestCase):
    def test_production_router_uses_the_project_skill(self):
        router = visual_plan._load_router_module()
        expected = (
            Path(__file__).resolve().parents[3]
            / "skill-development/hd-talking-head/scripts/broll_capability_router.py"
        )
        self.assertEqual(Path(router.__file__).resolve(), expected.resolve())

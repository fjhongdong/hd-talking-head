"""Validate documented data structures, not literal wording or headings."""
import json
import unittest
from pathlib import Path
from edit.hd.tools import avatar_profile

from edit.hd.tools.visual_strategy import (
    validate_visual_intent, validate_visual_strategy, validate_shot_recipe_v2,
)


class SchemaExampleTests(unittest.TestCase):
    def test_documented_example_uses_current_production_schemas(self):
        path = Path(__file__).resolve().parents[1] / "references/examples/schema-v2-example.json"
        example = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(validate_visual_intent(example["intent"]), example["intent"])
        self.assertEqual(validate_visual_strategy(example["intent"], example["strategy"]), example["strategy"])
        self.assertEqual(validate_shot_recipe_v2(example["recipe"]), example["recipe"])
        avatar_profile.validate_plan_avatars([
            {"start": 0, "end": 5, "visual_strategy": example["strategy"]}
        ], source_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()

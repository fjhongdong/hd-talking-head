from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from edit.hd.tests.test_aroll_overlay_pipeline import _overlay_segment
from edit.hd.tools import contract_artifacts, talkcraft_overlay, visual_canary


class TalkCraftOverlayBindingTests(unittest.TestCase):
    def test_binding_uses_approved_aroll_and_exact_segment_clock(self):
        segment = _overlay_segment()
        recipe = segment["shot_recipe"]
        component = recipe["components"][0]
        component.update(source_sha256="c" * 64, template_origin="custom_fallback")
        plan = {"segments": [segment]}
        brief = {"schema_version": 1,
                 "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-001", "start": 0, "end": 2},
                 "renderer_input": {"canvas": {"width": 1080, "height": 1920, "fps": 24, "frames": 48}}}
        with patch.object(visual_canary, "load_approved_visual_plan", return_value=plan), \
             patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": "a" * 64}), \
             patch.object(talkcraft_overlay, "source_identity", return_value="c" * 64):
            talkcraft_overlay.validate_source_binding(None, recipe, component, contract_artifacts.canonical_json_bytes(brief))
            for field, value in (("aroll_sha256", "b" * 64), ("start", .5), ("end", 3), ("segment_id", "seg-002")):
                changed = copy.deepcopy(brief)
                changed["source_binding"][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "binding changed"):
                    talkcraft_overlay.validate_source_binding(None, recipe, component, contract_artifacts.canonical_json_bytes(changed))
            for field, value in (("source_sha256", "d" * 64), ("template_origin", "verified_third_party")):
                changed = dict(component, **{field: value})
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "binding changed"):
                    talkcraft_overlay.validate_source_binding(None, recipe, changed, contract_artifacts.canonical_json_bytes(brief))

    def test_rejects_recipe_not_in_current_plan(self):
        segment = _overlay_segment()
        with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": []}):
            with self.assertRaisesRegex(ValueError, "approved segment"):
                talkcraft_overlay.validate_source_binding(None, segment["shot_recipe"], {},
                    contract_artifacts.canonical_json_bytes({"schema_version": 1, "source_binding": {}, "renderer_input": {}}))


if __name__ == "__main__":
    unittest.main()

"""Public contracts for the current direct-production workflow."""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
import _env
from edit.hd.tools import delivery_approval, preview_v2, state
import audit_job_completion

SKILL = Path(__file__).resolve().parents[1]

class CompletionContractTests(unittest.TestCase):
    def test_opening_has_formal_api_and_explicit_bgm_boundary(self):
        defaults = json.loads((SKILL / "references/production-defaults.json").read_text())
        self.assertEqual(defaults["opening"]["hold_frames"], 12)
        self.assertEqual(defaults["opening"]["transition_frames"], 0)
        self.assertFalse(defaults["background_music"])
        self.assertTrue({"opening", "music"}.issubset(inspect.signature(preview_v2.prepare_preview_v2).parameters))

    def test_delivery_identity_keeps_acceptance_separate_from_production(self):
        first = delivery_approval.receipt_paths({"sha256": "1" * 64})
        second = delivery_approval.receipt_paths({"sha256": "2" * 64})
        self.assertEqual(first, delivery_approval.receipt_paths({"sha256": "1" * 64}))
        self.assertNotEqual(first, second)
        self.assertNotEqual(first[0], first[1])
        self.assertTrue(callable(audit_job_completion.audit_job_completion))
        self.assertTrue(callable(delivery_approval.current_delivery_status))

    def test_template_qualification_does_not_add_a_production_canary_stage(self):
        registry = json.loads((SKILL / "references/verified-template-registry.json").read_text())
        self.assertTrue(registry["templates"])
        self.assertTrue(all(row.get("execution_qa") for row in registry["templates"]))
        self.assertNotIn("visual_canary", state.STAGE_IDS)
        self.assertEqual(len(state.STAGE_IDS), 11)
        self.assertEqual(state.STAGE_STATUSES, ("pending", "ready", "completed", "needs_revision", "blocked"))
        self.assertFalse(hasattr(state, "approve"))

if __name__ == "__main__":
    unittest.main()

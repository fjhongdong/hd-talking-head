"""End-state contracts for the one canonical Skill release."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


class CompletionContractTests(unittest.TestCase):
    def test_opening_has_formal_api_and_explicit_bgm_boundary(self):
        content = (SKILL / "references/cover-opening-bgm.md").read_text()
        for phrase in ("prepare_preview_v2(job, opening=", "hold_frames", "transition_frames",
                       "opening-manifest.json", "plans/body-subtitles.webm",
                       "music=approved_music_options", "music-audit.m4a", "revise", "ready_for_review"):
            self.assertIn(phrase, content)
        manifest = json.loads((SKILL / "references/dependency-manifest.json").read_text())
        preview = next(item for item in manifest["dependencies"] if item["id"] == "preview-runner")
        self.assertIn("validate_preview_opening", preview["api"])

    def test_material_lifecycle_and_audit_are_public_contracts(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        workspace = (SKILL / "references/job-workspace-contract.md").read_text(
            encoding="utf-8"
        )
        stages = (SKILL / "references/stage-contracts.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "material-usage.json",
            "confirmed_plan_hash",
            "workflow_revised",
            "scripts/audit_job_completion.py",
            "formal_complete",
            "legacy_external_approval",
            "incomplete",
            "inconsistent",
        ):
            self.assertIn(phrase, "\n".join((skill, workspace, stages)))

    def test_release_has_fourteen_verified_templates_and_keeps_job_canary_gate(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        qualification = (SKILL / "references/template-qualification.md").read_text(
            encoding="utf-8"
        )
        registry = json.loads(
            (SKILL / "references/verified-template-registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(registry["templates"]), 14)
        self.assertIn("五套本地 canonical", skill + qualification)
        self.assertIn("canary 人工审批门", skill + qualification)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from edit.hd.tests.test_render_span import v4_plan
from edit.hd.tests.test_talkcraft_contract import brief
from edit.hd.tools import (
    contract_artifacts,
    render_span,
    state,
    talkcraft_binding,
    talkcraft_contract,
    visual_plan,
)


class TalkCraftBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        source = self.root / "source.mp4"
        script = self.root / "script.md"
        source.write_bytes(b"source")
        script.write_text("测试文案", encoding="utf-8")
        self.job = state.create_job(
            self.root, source, script, profile="full-v2"
        )
        prerequisites = (
            ("inspect", "01-inspect/report.json"),
            ("content_analysis", "02-content-analysis/content-analysis.json"),
            ("cover_direction", "03-cover-direction/cover-direction.json"),
            ("cover", "04-cover/cover-report.json"),
            ("speech_cleanup", "05-speech-cleanup/word-transcript.json"),
            ("edit_structure", "06-edit-structure/edit-plan.json"),
        )
        for stage_id, relative in prerequisites:
            path = self.job.job_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            state.mark_ready(self.job, stage_id, (path,))
            state.approve(self.job, stage_id)

        self.registry_path = self.root / "registry.json"
        registry = json.loads(
            talkcraft_contract.DEFAULT_CARD_REGISTRY.read_text(encoding="utf-8")
        )
        production = registry["cards"][0]["production"]
        production.update(
            status="qualified",
            derived_entrypoint="edit/hd/integrations/talkcraft/runtime/render.mjs",
            implementation_sha256="b" * 64,
            adapter_version="1.0.0",
            qualification_id="c" * 64,
        )
        registry["cards"][1]["production"].update(
            status="pending_portrait_adapter",
            derived_entrypoint=None,
            implementation_sha256=None,
            input_adapter_sha256=None,
            adapter_version=None,
            qualification_id=None,
        )
        registry["qualification_policy"].update(
            state="partially_qualified", production_enabled=True
        )
        contract_artifacts.write_json_artifact(self.registry_path, registry)

        payload = brief()
        payload["registry"] = {
            "version": registry["registry_version"],
            "sha256": contract_artifacts.sha256_file(self.registry_path),
        }
        payload["render"].update(
            entrypoint="edit/hd/integrations/talkcraft/runtime/render.mjs",
            implementation_sha256="b" * 64,
            adapter_version="1.0.0",
            qualification_id="c" * 64,
        )
        self.plan = visual_plan.validate_visual_plan(
            v4_plan(payload["card_id"])
        )
        chunk = self.plan["render_spans"][0]["chunks"][0]
        span = self.plan["render_spans"][0]
        payload["owner"].update(
            visual_plan_sha256=self.plan["visual_plan_sha256"],
            spec_sha256=chunk["spec_sha256"],
            scene_brief_sha256=span["scene_brief_sha256"],
        )
        entry = {
            "brief": payload,
            "brief_sha256": contract_artifacts.sha256_json(payload),
        }
        unsigned = {
            "schema_version": "talkcraft-brief-bundle/v1",
            "owner": copy.deepcopy(payload["owner"]),
            "briefs": [entry],
        }
        self.bundle = {
            **unsigned,
            "bundle_sha256": contract_artifacts.sha256_json(unsigned),
        }
        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        bundle_path = (
            self.job.job_dir
            / "07-visual-direction/talkcraft-briefs/span-001/chunk-001.json"
        )
        contract_artifacts.write_json_artifact(plan_path, self.plan)
        contract_artifacts.write_json_artifact(bundle_path, self.bundle)
        state.mark_ready(
            self.job, "visual_direction", (plan_path, bundle_path)
        )
        state.approve(self.job, "visual_direction")
        self.job = state.load_job(self.job.job_dir)
        self.request = render_span.SpanExecutionRequest(
            self.plan, "span-001", "chunk-001"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_approved_bundle_binds_and_revalidates(self) -> None:
        binding = talkcraft_binding.bind_approved_brief_bundle(
            self.job,
            self.request,
            self.bundle,
            registry_path=self.registry_path,
        )
        self.assertEqual(binding["workflow_revision"], self.job.revision)
        self.assertEqual(
            binding["production_brief_bundle_sha256"],
            self.bundle["bundle_sha256"],
        )
        self.assertEqual(
            talkcraft_binding.revalidate_approved_binding(
                self.job.job_dir,
                self.request,
                self.bundle,
                binding,
                registry_path=self.registry_path,
            ),
            binding,
        )

    def test_stale_revision_and_unapproved_bundle_are_rejected(self) -> None:
        binding = talkcraft_binding.bind_approved_brief_bundle(
            self.job,
            self.request,
            self.bundle,
            registry_path=self.registry_path,
        )
        state.revise(self.job, "visual_direction", "test revision")
        with self.assertRaises(talkcraft_binding.TalkCraftBindingError):
            talkcraft_binding.revalidate_approved_binding(
                self.job.job_dir,
                self.request,
                self.bundle,
                binding,
                registry_path=self.registry_path,
            )


if __name__ == "__main__":
    unittest.main()

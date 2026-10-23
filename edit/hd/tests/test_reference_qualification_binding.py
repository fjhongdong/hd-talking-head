"""Candidate registry identity must survive process evidence and cache binding."""
from dataclasses import replace
from pathlib import Path
import unittest

from edit.hd.tools import broll_component_executor as executor


class ReferenceQualificationBindingTests(unittest.TestCase):
    def adapter(self):
        return executor.ReferenceProcessAdapter(
            adapter_id="relation-test", dependency_id="hd-talking-head-relation-motion",
            approved_executor="reference_adapter", dependency_root=Path('/dependency'),
            entrypoint="render.py", entrypoint_sha256="1" * 64,
            producer_version="1", primary_renderer="RelationMotion", renderer_version="1",
            artifact_media_type="video", launcher=Path('/python'), launcher_sha256="2" * 64,
            argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}",
                           "--output", "{output_path}"),
            brief_loader=lambda *_: b'{}', self_contained_wrapper=True,
            qualification_registry_path="assets/candidate/source-registry.json",
            qualification_registry_sha256="3" * 64,
        )

    def binding(self, adapter):
        probe = executor.ArtifactProbe(probe_id="test", probe_version="1", probe=lambda *_: {})
        return executor._adapter_binding_record(adapter, probe)

    def test_registry_identity_is_in_process_evidence_and_binding(self):
        adapter = self.adapter()
        expected = {"path": adapter.qualification_registry_path,
                    "sha256": adapter.qualification_registry_sha256}
        for record in (executor._base_process_evidence(adapter), self.binding(adapter)):
            self.assertEqual(record.get("qualification_registry"), expected)

    def test_changed_registry_cannot_share_a_binding(self):
        adapter = self.adapter()
        changed = replace(adapter, qualification_registry_sha256="4" * 64)
        self.assertNotEqual(self.binding(adapter), self.binding(changed))

    def test_unconfigured_legacy_binding_does_not_gain_new_fields(self):
        adapter = replace(self.adapter(), qualification_registry_path=None,
                          qualification_registry_sha256=None)
        self.assertNotIn("qualification_registry", self.binding(adapter))
        self.assertNotIn("qualification_registry", executor._base_process_evidence(adapter))

    def test_evidence_validation_requires_exact_candidate_registry_identity(self):
        adapter = self.adapter()
        binding = self.binding(adapter)
        evidence = executor._base_process_evidence(adapter)
        _, _, argv = executor._canonical_process_argv(
            adapter=adapter, entrypoint=adapter.entrypoint, staging_job_path="stage.mp4")
        evidence.update(invocation_id="test-run", brief_sha256="5" * 64,
                        argv=argv, pid=42, exit_code=0, stdout_sha256="6" * 64,
                        stderr_sha256="7" * 64, descendants_terminated=False,
                        output_job_path="out.mp4", output_sha256="8" * 64,
                        probe_id="test", probe_version="1")
        arguments = dict(component={"kind": "code_generated", "executor": "reference_adapter",
                                    "brief_sha256": "5" * 64},
                         binding=binding, adapter_staging_job_path="stage.mp4",
                         output_job_path="out.mp4", output_sha256="8" * 64,
                         job_dir=Path('/synthetic-job'), code="BROLL_DEPENDENCY_UNBOUND")
        self.assertEqual(executor._validate_invocation_evidence(evidence, **arguments), evidence)
        for replacement in (None, {"path": adapter.qualification_registry_path, "sha256": "9" * 64},
                            {"path": "assets/other.json", "sha256": adapter.qualification_registry_sha256}):
            altered = dict(evidence)
            if replacement is None:
                altered.pop("qualification_registry", None)
            else:
                altered["qualification_registry"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(executor.BrollComponentExecutionError):
                executor._validate_invocation_evidence(altered, **arguments)
        legacy = replace(adapter, qualification_registry_path=None, qualification_registry_sha256=None)
        arguments["binding"] = self.binding(legacy)
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor._validate_invocation_evidence(evidence, **arguments)

"""Candidate registry bytes stay pinned across execution and replay."""
from __future__ import annotations

from dataclasses import replace
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from edit.hd.tests import test_broll_component_executor as fixtures
from edit.hd.tools import broll_component_executor as executor


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QualificationRegistryFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.case = fixtures.CodeDependencyExecutionTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.dependency = self.case.root / "dependency-html-video"
        self.registry_relative = "qualification/source-registry.json"
        self.registry = self.dependency / self.registry_relative
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes(b'{"candidate":"one"}\n')

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def adapter(self, brief: bytes = b"{}", script: str = "pass"):
        base = self.case._adapter(brief, script, dependency_id="html-video")
        return replace(
            base,
            qualification_registry_path=self.registry_relative,
            qualification_registry_sha256=_sha(self.registry),
        )

    def test_freeze_rejects_symlink_escape_and_closes_its_descriptor(self) -> None:
        adapter = self.adapter()
        frozen = executor._freeze_qualification_registry(adapter)
        descriptor = frozen.descriptor
        frozen.close()
        with self.assertRaises(OSError) as caught:
            os.fstat(descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)

        outside = self.root / "outside.json"
        outside.write_bytes(self.registry.read_bytes())
        self.registry.unlink()
        self.registry.symlink_to(outside)
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor._freeze_qualification_registry(adapter)
        escaped = replace(adapter, qualification_registry_path="../outside.json")
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor._freeze_qualification_registry(escaped)

    def test_export_rechecks_candidate_after_read_and_closes_descriptor(self):
        adapter = self.adapter()
        request = fixtures._request(fixtures._code_component(b'{}'))
        adapters = {'code_generated': {'html-video': adapter}, 'artifact_probe': fixtures._artifact_probe()}
        captured = []
        real_freeze = executor._freeze_qualification_registry
        def freezing(value):
            result = real_freeze(value)
            captured.append(result.descriptor)
            return result
        def changed(*args, **kwargs):
            self.registry.write_bytes(b'changed')
            return {}
        with mock.patch.object(executor, '_freeze_qualification_registry', side_effect=freezing), \
             mock.patch.object(executor, '_try_replay_transaction', side_effect=changed):
            with self.assertRaises(executor.BrollComponentExecutionError):
                executor.export_published_execution_binding(self.case.job, request, adapters=adapters)
        self.assertEqual(len(captured), 1)
        with self.assertRaises(OSError):
            os.fstat(captured[0])

    def test_verify_detects_replacement_same_inode_rewrite_and_deletion(self) -> None:
        for mutation in ("replace", "rewrite", "delete"):
            with self.subTest(mutation=mutation):
                self.registry.unlink(missing_ok=True)
                self.registry.write_bytes(b'{"candidate":"one"}\n')
                adapter = self.adapter()
                frozen = executor._freeze_qualification_registry(adapter)
                try:
                    if mutation == "replace":
                        replacement = self.registry.with_suffix(".next")
                        replacement.write_bytes(self.registry.read_bytes())
                        os.replace(replacement, self.registry)
                    elif mutation == "rewrite":
                        self.registry.write_bytes(b'{"candidate":"two"}\n')
                    else:
                        self.registry.unlink()
                    with self.assertRaises(executor.BrollComponentExecutionError):
                        executor._verify_frozen_qualification_registry(frozen)
                finally:
                    frozen.close()

    def test_process_registry_change_fails_and_closes_frozen_descriptor(self) -> None:
        brief = b"{}"
        script = (
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args()\n"
            f"Path({str(self.registry)!r}).write_bytes(b'changed')\n"
            "Path(a.output).write_bytes(b'output')\n"
        )
        adapter = self.adapter(brief, script)
        captured = []
        real_freeze = executor._freeze_qualification_registry

        def freezing(value):
            result = real_freeze(value)
            captured.append(result)
            return result

        policy = mock.Mock()
        with (
            mock.patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy),
            mock.patch.object(executor, "_freeze_qualification_registry", side_effect=freezing),
            self.assertRaises(executor.BrollComponentExecutionError),
        ):
            self.case._execute(brief, adapter, dependency_id="html-video")
        self.assertEqual(len(captured), 1)
        with self.assertRaises(OSError) as caught:
            os.fstat(captured[0].descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_published_replay_freezes_verifies_then_closes_candidate_registry(self) -> None:
        brief = b"{}"
        script = (
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args(); Path(a.output).write_bytes(b'replay-output')\n"
        )
        adapter = self.adapter(brief, script)
        policy = mock.Mock()
        with mock.patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy):
            first = self.case._execute(brief, adapter, dependency_id="html-video")

        # Real subprocess/journal, synthetic output/probe: this is export coverage,
        # not native MP4 qualification or approval of the candidate registry.
        request = fixtures._request(fixtures._code_component(brief))
        adapters = {'code_generated': {'html-video': adapter}, 'artifact_probe': fixtures._artifact_probe()}
        def snapshot():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.case.job.job_dir.rglob('*') if p.is_file()}
        before = snapshot()
        with mock.patch.object(executor, '_run_reference_process', side_effect=AssertionError('export rerendered')):
            exported = executor.export_published_execution_binding(self.case.job, request, adapters=adapters)
        self.assertEqual(exported['state'], 'published')
        self.assertEqual(exported['artifact_sha256'], fixtures._sha256(fixtures._canonical(dict(first))))
        self.assertEqual(exported['adapter_binding']['qualification_registry'],
                         dict(first.invocation_evidence['qualification_registry']))
        self.assertEqual(exported['output_sha256'], first.output_sha256)
        self.assertEqual(snapshot(), before)
        from edit.hd.tests.test_relation_qualification_content import verifier
        receipt = {'published_execution': exported,
                   'artifact': json.loads(fixtures._canonical(dict(first)))}
        verifier._verify_published_execution(receipt, request.recipe)
        for mutation in ('index', 'literal'):
            changed = json.loads(json.dumps(exported))
            template = changed['adapter_binding']['argv_template']
            if mutation == 'index':
                template[0]['index'] = False
            else:
                next(item for item in template if item['role'] == 'literal')['value'] = '--wrong'
            with self.subTest(argv=mutation), self.assertRaises(verifier.RegistryError):
                verifier._verify_published_execution(
                    {**receipt, 'published_execution': changed}, request.recipe)
        for registry in (None, {'path': 'other.json', 'sha256': '0' * 64}):
            bad = {**receipt, 'published_execution': {**exported, 'adapter_binding': {
                **exported['adapter_binding'], 'qualification_registry': registry}}}
            with self.subTest(registry=registry), self.assertRaises(verifier.RegistryError):
                verifier._verify_published_execution(bad, request.recipe)
        for field in ('adapter_id', 'dependency_id', 'entrypoint', 'launcher_sha256', 'probe_id'):
            bad = {**receipt, 'published_execution': {**exported, 'adapter_binding': {
                **exported['adapter_binding'], field: 'wrong'}}}
            with self.subTest(binding_field=field), self.assertRaises(verifier.RegistryError):
                verifier._verify_published_execution(bad, request.recipe)
        for field, value in (('byte_count', False), ('output_sha256', 123), ('job_path', '../escape')):
            malformed = {**dict(first), field: value}
            paired = {**exported, 'output_job_path' if field == 'job_path' else field: value,
                      'artifact_sha256': hashlib.sha256(json.dumps(malformed, ensure_ascii=False,
                          sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}
            with self.subTest(paired_field=field), self.assertRaises(verifier.RegistryError):
                verifier._verify_published_execution(
                    {'artifact': malformed, 'published_execution': paired}, request.recipe)
        for field in ('input_sha256', 'recipe_sha256', 'artifact_sha256', 'output_sha256', 'component_id'):
            bad = {**receipt, 'published_execution': {**exported, field: 'wrong'}}
            with self.subTest(field=field), self.assertRaises(verifier.RegistryError):
                verifier._verify_published_execution(bad, request.recipe)
        journal = next(self.case.job.job_dir.rglob('*.transaction.json'))
        original = journal.read_bytes()
        for changes in ({'state': 'complete'}, {'input_sha256': '0' * 64}):
            altered = {**json.loads(original), **changes}
            journal.write_bytes(fixtures._canonical(altered) + b'\n')
            rejected_before = snapshot()
            with self.subTest(changes=changes), self.assertRaises(executor.BrollComponentExecutionError):
                executor.export_published_execution_binding(self.case.job, request, adapters=adapters)
            self.assertEqual(snapshot(), rejected_before)
            journal.write_bytes(original)

        events = []
        captured = []
        real_freeze = executor._freeze_qualification_registry
        real_verify = executor._verify_frozen_qualification_registry
        real_replay = executor._try_replay_transaction

        def freezing(value):
            events.append("freeze")
            result = real_freeze(value)
            captured.append(result)
            return result

        def verifying(value):
            events.append("verify")
            return real_verify(value)

        def replaying(*args, **kwargs):
            events.append("replay")
            return real_replay(*args, **kwargs)

        with (
            mock.patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy),
            mock.patch.object(executor, "_freeze_qualification_registry", side_effect=freezing),
            mock.patch.object(executor, "_verify_frozen_qualification_registry", side_effect=verifying),
            mock.patch.object(executor, "_try_replay_transaction", side_effect=replaying),
        ):
            replay = self.case._execute(brief, adapter, dependency_id="html-video")
        self.assertEqual(replay.output_sha256, first.output_sha256)
        self.assertEqual(events[:4], ["freeze", "verify", "replay", "verify"])
        with self.assertRaises(OSError) as caught:
            os.fstat(captured[0].descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_registry_change_around_real_publish_rolls_back_final_and_cannot_replay(self) -> None:
        original = self.registry.read_bytes()
        real_publish = executor._publish_transaction
        policy = mock.Mock()
        for timing in ("before", "after"):
            with self.subTest(timing=timing):
                self.registry.write_bytes(original)
                marker = self.root / f"{timing}.calls"
                brief = ("{\"case\":\"" + timing + "\"}").encode()
                script = (
                    "from pathlib import Path\n"
                    "import argparse\n"
                    "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
                    "a=p.parse_args()\n"
                    f"m=Path({str(marker)!r}); m.write_text(m.read_text()+'x' if m.exists() else 'x')\n"
                    "Path(a.output).write_bytes(b'publish-output')\n"
                )
                adapter = self.adapter(brief, script)
                frozen = []
                real_freeze = executor._freeze_qualification_registry

                def freezing(value):
                    result = real_freeze(value)
                    frozen.append(result)
                    return result

                def publishing(*args, **kwargs):
                    if timing == "before":
                        self.registry.write_bytes(b"changed-before-publish")
                    result = real_publish(*args, **kwargs)
                    if timing == "after":
                        self.registry.write_bytes(b"changed-after-publish")
                    return result

                visible_before = set(self.case.job.job_dir.rglob("*.mov"))
                with (
                    mock.patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy),
                    mock.patch.object(executor, "_freeze_qualification_registry", side_effect=freezing),
                    mock.patch.object(executor, "_publish_transaction", side_effect=publishing),
                    self.assertRaises(executor.BrollComponentExecutionError) as caught,
                ):
                    self.case._execute(
                        brief, adapter, dependency_id="html-video",
                        component_id=f"publish-{timing}",
                    )
                self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
                self.assertEqual(set(self.case.job.job_dir.rglob("*.mov")), visible_before)
                self.assertEqual(marker.read_text(), "x")
                with self.assertRaises(OSError) as closed:
                    os.fstat(frozen[0].descriptor)
                self.assertEqual(closed.exception.errno, errno.EBADF)

                self.registry.write_bytes(original)
                with mock.patch(
                    "edit.hd.tools.visual_plan._load_router_module", return_value=policy
                ):
                    self.case._execute(
                        brief, adapter, dependency_id="html-video",
                        component_id=f"publish-{timing}",
                    )
                self.assertEqual(marker.read_text(), "xx", "failed publish was replayed")


if __name__ == "__main__":
    unittest.main()

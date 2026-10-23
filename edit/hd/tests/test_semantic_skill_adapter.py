"""The unique master Skill exposes SemanticState without registering it."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / 'skill-development/hd-talking-head/scripts/semantic_state_adapter.py'


class SemanticSkillAdapterTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('semantic_skill_adapter', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_binding_uses_candidate_identity_and_current_approved_report(self):
        module = self.module()
        payload = b'{"motion":{"family":"feedback"}}'
        template_id = 'hd-talking-head/semantic-state-feedback'
        template = {key: key for key in module.PROVENANCE}
        template['template_id'] = template_id
        report = {'template_id': template_id, 'brief_sha256': hashlib.sha256(payload).hexdigest(),
                  'semantic_motion': {'execution_status': 'planning_only'},
                  'template_request': {'semantic_family': 'feedback', 'information_units': 2,
                                       'numeric_values': [], 'numeric_scale': 'not_applicable'}}
        adapter = SimpleNamespace(dependency_id=module.DEPENDENCY_ID, entrypoint=module.ENTRY,
            producer_version=module.VERSION, primary_renderer='SemanticState',
            renderer_version=module.VERSION, launcher=Path('/runtime/python'),
            runtime_contracts={'node': {'path': '/runtime/node', 'sha256': 'a' * 64}})
        with mock.patch.object(module, '_registry_template', return_value=template), \
             mock.patch('edit.hd.tools.semantic_state_binding.bind_brief', return_value=report) as bind:
            result = module.create_binding(adapter, object(), payload,
                registry_path='candidate.json', registry_sha256='b' * 64)
        bind.assert_called_once_with(mock.ANY, payload, node_executable=Path('/runtime/node'),
                                     node_sha256='a' * 64, template_id=template_id)
        self.assertEqual(result['template_id'], template_id)
        self.assertEqual(result['invocation_record']['semantic_motion'], report['semantic_motion'])
        self.assertEqual(result['invocation_record']['template_request'], report['template_request'])

    def test_registry_hash_and_parser_consume_one_snapshot(self):
        module = self.module()
        source_sha = module._sha(module.SKILL / module.ENTRY)
        old = {key: key for key in module.PROVENANCE}
        old.update(template_id=module.TEMPLATES['feedback'], source_entrypoint=module.ENTRY,
                   source_sha256=source_sha, sample_sha256='1' * 64)
        new = dict(old, sample_sha256='2' * 64)
        with tempfile.TemporaryDirectory(dir=module.SKILL) as directory:
            registry = Path(directory) / 'registry.json'
            registry.write_text(json.dumps({'schema_version': 1, 'templates': [old]}))
            relative = registry.relative_to(module.SKILL).as_posix()
            expected_sha = module._sha(registry)
            changed = False
            real_read = module._read_snapshot
            def read_then_replace(path, *args, **kwargs):
                nonlocal changed
                result = real_read(path, *args, **kwargs)
                if Path(path) == registry and not changed:
                    changed = True
                    registry.write_text(json.dumps({'schema_version': 1, 'templates': [new]}))
                return result
            with mock.patch.object(module, '_read_snapshot', side_effect=read_then_replace):
                selected = module._registry_template(old['template_id'], relative, expected_sha)
            self.assertTrue(changed)
            self.assertEqual(selected['sample_sha256'], old['sample_sha256'])

    def test_probe_executes_a_private_snapshot_not_a_replaced_path(self):
        module = self.module()
        payload = {'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920,
            'r_frame_rate': '24/1', 'avg_frame_rate': '24/1', 'sample_aspect_ratio': '1:1',
            'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'duration': '5.0',
            'nb_read_frames': '120'}], 'format': {'format_name': 'mov,mp4'}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable, marker = root / 'ffprobe', root / 'attacker-ran'
            executable.write_text('#!/usr/bin/python3\nimport json\nprint(' + repr(json.dumps(payload)) + ')\n')
            executable.chmod(0o700)
            probe = module.create_artifact_probe(ffprobe_executable=executable)
            malicious = ('#!/usr/bin/python3\nfrom pathlib import Path\nimport json\n'
                         f'Path({str(marker)!r}).write_text("ran")\nprint({json.dumps(payload)!r})\n')
            real_run = subprocess.run
            commands = []
            def replace_at_exec(command, **kwargs):
                commands.append(command)
                if len(commands) == 1:
                    executable.write_text(malicious)
                    executable.chmod(0o700)
                return real_run(command, **kwargs)
            with mock.patch('subprocess.run', side_effect=replace_at_exec), \
                 self.assertRaisesRegex(ValueError, 'changed during probe'):
                probe.probe(root / 'input.mp4', 'video', {'alpha': False})
            self.assertEqual(len(commands), 1)
            self.assertNotEqual(Path(commands[0][0]), executable)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()

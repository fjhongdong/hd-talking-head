"""Operation-local reuse must follow media and source identity, not Job revision."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _env
from edit.hd.tools import startup


class NativeResultReuseTests(unittest.TestCase):
    def test_restored_source_changes_invalidate_selected_source_facts(self):
        import motion_native_skill_adapter as native
        with tempfile.TemporaryDirectory() as folder, startup.operation_scope() as operation:
            root = Path(folder).resolve()
            source = root / 'vendor/video-shotcraft'; source.mkdir(parents=True)
            entry = source / 'index.js'; entry.write_bytes(b'original source')
            record = {'commit': 'fixture', 'source_root': 'vendor/video-shotcraft',
                      'files': {'index.js': hashlib.sha256(entry.read_bytes()).hexdigest()}}
            identity = root / 'references/video-shotcraft-native-source.json'
            identity.parent.mkdir(); identity.write_text(json.dumps(record))
            index = root / 'archives/sources/index.json'; index.parent.mkdir(parents=True)
            index.write_text(json.dumps({'repositories': [{'path': 'vendor/video-shotcraft',
                'files': record['files'], 'archives': ['fixture.part']}]}))
            manifest = {'files': {identity.relative_to(root).as_posix(): '0' * 64,
                                  index.relative_to(root).as_posix(): '0' * 64}}
            (root / 'release-manifest.json').write_text(json.dumps(manifest))
            snapshot = startup._release_snapshot(root, manifest)
            operation.releases[(str(root), 'fixture')] = {'manifest': manifest, 'snapshot': snapshot}
            pinned = ('video-shotcraft', 'fixture', hashlib.sha256(identity.read_bytes()).hexdigest())
            with mock.patch.dict(native.SOURCES, {'video-shotcraft': pinned}):
                self.assertEqual(native.source_root(root, dependency_id='video-shotcraft'), source)
                self.assertEqual(native.source_root(root, dependency_id='video-shotcraft'), source)
                result_key = ('native-result-facts', str(root), 'validator', ('motion', 'video-shotcraft'), 'fixture')
                operation.memo[result_key] = 'prior result'
                entry.write_bytes(b'changed source')
                self.assertEqual(startup._release_snapshot(root, manifest, previous=snapshot), snapshot)
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    native.source_root(root, dependency_id='video-shotcraft')
                self.assertNotIn(result_key, operation.memo)
                metrics = operation.metrics()['native_facts']
                self.assertEqual(metrics['source_fact_hits'], 1)
                self.assertEqual(metrics['source_fact_invalidations'], 1)
                identity.write_text('{"source_root": "untrusted-directory"}')
                with mock.patch.object(Path, 'rglob') as enumerate_source:
                    with self.assertRaisesRegex(ValueError, 'identity record changed'):
                        native.source_root(root, dependency_id='video-shotcraft')
                    enumerate_source.assert_not_called()

    def test_input_facts_share_across_modules_and_follow_input_and_tool_changes(self):
        import run_stage
        from native_result_reuse import input_file_digest
        from test_talkcraft_skill_adapter import brief as make_brief
        native, consumer = (run_stage._module('talkcraft_skill_adapter') for _ in range(2))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            brief = make_brief()
            speech_file = root / 'voice.wav'; speech_file.write_bytes(b'voice')
            tool = root / 'ffprobe'; tool.write_bytes(b'probe tool')
            probe = json.dumps({'streams': [{'codec_type': 'audio'}], 'format': {'duration': '2'}})
            with mock.patch.object(startup, '_operation_cache', side_effect=lambda _: startup.current_operation().memo), \
                 mock.patch('native_result_reuse.shutil.which', return_value=str(tool)), \
                 mock.patch.object(native.subprocess, 'check_output', return_value=probe) as speech:
                with startup.operation_scope() as operation:
                    native._inputs(root, brief); consumer._inputs(root, brief)
                    self.assertEqual(speech.call_count, 1)
                    self.assertEqual(input_file_digest(root, speech_file, cache=operation.memo), brief['speech']['sha256'])
                    self.assertEqual(operation.metrics()['native_facts']['input_hashes'], 1)
                    tool.write_bytes(b'new probe tool')
                    consumer._inputs(root, brief)
                    self.assertEqual(speech.call_count, 2)
                    speech_file.write_bytes(b'other')
                    for _ in range(2):
                        with self.assertRaisesRegex(ValueError, 'evidence changed'):
                            consumer._inputs(root, brief)
                    self.assertEqual(speech.call_count, 2)
                    speech_file.write_bytes(b'voice')
                    native._inputs(root, brief)
                    self.assertEqual(speech.call_count, 3)
                    metrics = operation.metrics()['native_facts']
                    self.assertEqual(metrics['input_probes'], 3)
                    self.assertEqual(metrics['input_fact_hits'], 1)
                    self.assertEqual(metrics['input_hash_fact_hits'], 1)
                    self.assertGreaterEqual(metrics['input_fact_invalidations'], 2)
                with startup.operation_scope():
                    native._inputs(root, brief)
                    self.assertEqual(speech.call_count, 4)

    def test_talkcraft_inspection_and_load_share_probe_but_keep_current_expectations(self):
        import run_stage
        native = run_stage._module('talkcraft_skill_adapter')
        consumer = run_stage._module('talkcraft_skill_adapter')
        self.assertIsNot(native._inspect_result, consumer._inspect_result)
        from test_talkcraft_skill_adapter import brief as make_brief
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            brief = make_brief()
            project = root / brief['project_directory']; project.mkdir(parents=True)
            source = project / 'index.html'; source.write_bytes(b'current scene')
            media = project / 'movie.mp4'; media.write_bytes(b'movie')
            (root / 'voice.wav').write_bytes(b'voice')
            payload = json.dumps(brief).encode()
            record = root / brief['result_record_path']; record.parent.mkdir(parents=True)
            renderer = record.parent / 'renderer-package.json'; renderer.write_text('{"version": "1"}')
            original = native.source_root()
            call = {'request_sha256': hashlib.sha256(payload).hexdigest(), 'exit_code': 0,
                    'upstream_commit': native.UPSTREAM_COMMIT,
                    'native_script_sha256': native.sha(original / native.NATIVE_RENDER),
                    'output': media.relative_to(root).as_posix(), 'renderer_version': '1',
                    'renderer_package': native.descriptor(root, renderer),
                    'project_files': [native.descriptor(root, source)]}
            call_file = record.parent / 'render-call.json'; call_file.write_text(json.dumps(call))
            result = {'schema_version': 2, 'status': 'completed', 'dependency_id': native.DEPENDENCY_ID,
                      'job_id': brief['job_id'], 'card_id': brief['card_id'],
                      'upstream_commit': native.UPSTREAM_COMMIT, 'request_sha256': call['request_sha256'],
                      'media_probe': brief['composition'], 'renderer_version': '1',
                      'render_call': native.descriptor(root, call_file), 'media': native.descriptor(root, media),
                      'native_card_lint': {'script_sha256': native.sha(original / 'scripts/card_lint.py'), 'exit_code': 0}}
            record.write_text(json.dumps(result))
            expected = {'path': brief['result_record_path'], 'sha256': native.sha(record), 'bytes': record.stat().st_size}
            speech_probe = json.dumps({'streams': [{'codec_type': 'audio'}], 'format': {'duration': '2'}})
            with startup.operation_scope(), \
                 mock.patch.object(startup, '_operation_cache', side_effect=lambda _: startup.current_operation().memo), \
                 mock.patch.object(native.subprocess, 'check_output', return_value=speech_probe) as speech, \
                 mock.patch.object(native, 'probe', return_value=brief['composition']) as output, \
                 mock.patch.object(consumer, 'probe', return_value=brief['composition']) as consumer_output:
                inspected = native.inspect_result(root, payload)
                inspected['renderer_version'] = 'caller mutation'
                self.assertEqual(consumer.load_result(root, payload, expected_record=expected,
                                 expected_renderer_version='1'), result)
                self.assertEqual((speech.call_count, output.call_count), (1, 1))
                consumer_output.assert_not_called()
                with self.assertRaisesRegex(ValueError, 'frozen version'):
                    native.load_result(root, payload, expected_record={**expected, 'sha256': '0' * 64},
                                       expected_renderer_version='1')
                with self.assertRaisesRegex(ValueError, 'frozen component'):
                    native.load_result(root, payload, expected_record=expected, expected_renderer_version='other')
                self.assertEqual((speech.call_count, output.call_count), (1, 1))
                changed = {**brief, 'authorization': {'paid_generation': True}}
                with self.assertRaisesRegex(ValueError, 'differs from its request'):
                    native.inspect_result(root, json.dumps(changed).encode())
                self.assertEqual(speech.call_count, 1)
                media.write_bytes(b'other')
                with self.assertRaisesRegex(ValueError, 'evidence changed'):
                    native.inspect_result(root, payload)
                self.assertEqual(speech.call_count, 1)
                media.write_bytes(b'movie')
                source.write_bytes(b'changed scene')
                with self.assertRaisesRegex(ValueError, 'evidence changed'):
                    native.inspect_result(root, payload)
                self.assertEqual(speech.call_count, 1)

    def test_unchanged_facts_reuse_and_dependencies_invalidate(self):
        from native_result_reuse import inspect_unchanged
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'native-projects/scene'
            project.mkdir(parents=True)
            source = project / 'index.html'; source.write_bytes(b'first')
            media = project / 'out.mp4'; media.write_bytes(b'media')
            speech = root / 'speech.wav'; speech.write_bytes(b'voice')
            renderer = root / 'renderer.json'; renderer.write_text('{"version": "1"}')
            call = root / 'render-call.json'
            call.write_text(json.dumps({'renderer_package': {'job_path': 'renderer.json'}}))
            brief = {'job_id': 'test', 'project_directory': 'native-projects/scene',
                     'speech': {'job_path': 'speech.wav'}}
            result = {'renderer_version': 'renderer-1', 'media': {'job_path': 'native-projects/scene/out.mp4'},
                      'render_call': {'job_path': 'render-call.json'}}
            payload = json.dumps(brief).encode(); data = json.dumps(result).encode()
            checked = mock.Mock(return_value=result)
            def validate(*args):
                return checked(*args)
            def inspect():
                return inspect_unchanged(_env.PROJECT, root, payload, data, brief, validate)
            with mock.patch.object(startup, '_operation_cache', side_effect=lambda _: startup.current_operation().memo):
                with startup.operation_scope():
                    inspect(); inspect()
                    self.assertEqual(checked.call_count, 1)
                    # An ordinary Job update has no bearing on unchanged native media.
                    (root / 'job.json').write_text('{"revision": 2}')
                    inspect(); self.assertEqual(checked.call_count, 1)
                    for target in (media, source, speech, renderer):
                        old = target.stat()
                        target.write_bytes(b'other')
                        os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
                        inspect()
                    self.assertEqual(checked.call_count, 5)
                    call.write_text(call.read_text() + ' ')
                    inspect(); self.assertEqual(checked.call_count, 6)
                    (project / 'new-source.js').write_text('new source')
                    inspect(); self.assertEqual(checked.call_count, 7)
                    source.unlink(); source.write_bytes(b'other')
                    inspect(); self.assertEqual(checked.call_count, 8)
                    source.unlink(); source.symlink_to(speech)
                    inspect(); inspect(); self.assertEqual(checked.call_count, 10)
                    media.unlink()
                    inspect(); self.assertEqual(checked.call_count, 11)
                with startup.operation_scope():
                    inspect(); self.assertEqual(checked.call_count, 12)

    def test_failures_and_missing_identity_never_reuse(self):
        from native_result_reuse import inspect_unchanged
        with tempfile.TemporaryDirectory() as folder, startup.operation_scope():
            root = Path(folder); (root / 'scene').mkdir()
            brief = {'job_id': 'test', 'project_directory': 'scene'}
            checked = mock.Mock(side_effect=ValueError('changed'))
            def validate(*args):
                return checked(*args)
            with mock.patch.object(startup, '_operation_cache', return_value=startup.current_operation().memo):
                for _ in range(2):
                    with self.assertRaises(ValueError):
                        inspect_unchanged(_env.PROJECT, root, b'brief', b'{"renderer_version":"1"}', brief, validate)
                self.assertEqual(checked.call_count, 2)
                checked.side_effect = None; checked.return_value = {}
                for _ in range(2):
                    inspect_unchanged(_env.PROJECT, root, b'brief', b'{}', brief, validate)
                self.assertEqual(checked.call_count, 4)


if __name__ == '__main__':
    unittest.main()

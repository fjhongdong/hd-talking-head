import hashlib
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_job_completion.py'
spec = importlib.util.spec_from_file_location('completion_audit_music', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def digest(value):
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')) + '\n').encode()).hexdigest()


class MusicCompletionAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(audit, '_music_evidence'), 'missing read-only music completion gate')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = self.root / 'job'
        self.stages = {'preview': {'artifacts': []}}
        self.delivery = {'job_id': 'job', 'final_sha256': 'f' * 64,
                         'background_music': True, 'artifacts': {}}
        self.probe = {'audio_streams': 1, 'duration_seconds': 2, 'audio_duration_seconds': 2}
        for name in ('music', 'license'):
            (self.root / name).write_bytes(name.encode())
        self.plan = {'schema_version': 1, 'job_id': 'job', 'fps': 24,
                     'total_frames': 48, 'body_offset_frames': 0,
                     'options': {'user_confirmation': '本次确认',
                                 'material_sha256': hashlib.sha256(b'music').hexdigest(),
                                 'license_sha256': hashlib.sha256(b'license').hexdigest()}}
        self.plan['options'].update({'material_id': 'music', 'license_material_id': 'license',
            'title': 'Title', 'author': 'Author', 'source': 'User provided',
            'selection': {'start_frame': 0, 'end_frame': 96, 'crossfade_frames': 4},
            'mix': {'voice_gain_db': 0, 'music_gain_db': -15, 'duck_threshold': .1,
                    'duck_ratio': 4, 'duck_attack_ms': 20, 'duck_release_ms': 200,
                    'fade_in_frames': 4, 'fade_out_frames': 4}})
        voice = self.job / '06-edit-structure/edited-aroll.mp4'
        voice.parent.mkdir(parents=True)
        voice.write_bytes(b'voice')
        self.voice_sha = hashlib.sha256(b'voice').hexdigest()
        self.stages['edit_structure'] = {'status': 'approved', 'artifacts': [{
            'path': '06-edit-structure/edited-aroll.mp4', 'bytes': 5, 'sha256': self.voice_sha}]}
        for name in ('music', 'license'):
            self.plan[name] = {'path': name, 'sha256': hashlib.sha256(name.encode()).hexdigest(),
                               'bytes': len(name), 'material_id': name}
        self.plan['music_plan_sha256'] = digest(self.plan)
        attachments = {'music-audit.m4a': b'audit', 'music-license-source': b'license',
                       'music-credits.txt': b'credits'}
        self.music = {'schema_version': 1, 'plan': self.plan, 'voice_sha256': self.voice_sha,
                      'preview_sha256': 'f' * 64, 'listening_approval': 'required_at_preview',
                      'metrics': {name: {'integrated_lufs': -20, 'true_peak_dbtp': -2}
                                  for name in ('final', 'music')},
                      'attachments': {n: hashlib.sha256(v).hexdigest() for n, v in attachments.items()}}
        for name, value in attachments.items():
            self.publish(name, value)
        self.refresh()

    def publish(self, name, data):
        for folder in ('11-preview', '12-delivery'):
            path = self.job / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        record = {'path': '11-preview/' + name, 'bytes': len(data),
                  'sha256': hashlib.sha256(data).hexdigest()}
        records = self.stages['preview']['artifacts']
        records[:] = [r for r in records if r['path'] != record['path']]
        records.append(record)
        output_name = 'qa/qa-report.json' if name == 'qa-report.json' else name
        if output_name != name:
            target = self.job / '12-delivery' / output_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.delivery['artifacts'][output_name] = {'source': record,
            'output': {**record, 'path': output_name}}

    def refresh(self):
        self.music.pop('music_manifest_sha256', None)
        self.music['music_manifest_sha256'] = digest(self.music)
        self.publish('music-manifest.json', json.dumps(self.music).encode())
        qa = {'background_music': True, 'audio_mix_layers': 2,
              'audio_source_sha256': self.voice_sha,
              'music_manifest_sha256': self.music['music_manifest_sha256'],
              'preview_sha256': 'f' * 64, 'media': {'frames': 48}}
        self.publish('qa-report.json', json.dumps(qa).encode())

    def check(self):
        return audit._music_evidence(self.root, self.job, self.delivery, self.stages, self.probe)

    def test_valid_music_and_no_music(self):
        self.assertTrue(self.check())
        self.assertFalse(audit._music_evidence(self.root, self.root / 'empty',
                         {'artifacts': {}}, {}, None))

    def test_reject_tamper_and_clock_and_silent_metrics(self):
        for field, value in (('preview_sha256', '0' * 64), ('listening_approval', ''),
                             ('metrics', {'final': {'integrated_lufs': -20, 'true_peak_dbtp': 1},
                                          'music': {'integrated_lufs': -61, 'true_peak_dbtp': -2}})):
            with self.subTest(field=field):
                old = self.music[field]
                self.music[field] = value
                self.refresh()
                with self.assertRaises(audit.JobCompletionAuditError):
                    self.check()
                self.music[field] = old
        self.refresh()
        self.probe['audio_streams'] = 2
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()

    def test_partial_music_cannot_disappear(self):
        (self.job / '12-delivery/music-manifest.json').unlink()
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()

    def test_changed_source_or_attachment_rejected(self):
        for path in (self.root / 'music', self.job / '12-delivery/music-audit.m4a'):
            old = path.read_bytes()
            path.write_bytes(b'changed')
            with self.assertRaises(audit.JobCompletionAuditError):
                self.check()
            path.write_bytes(old)

    def test_plan_and_qa_and_probe_fail_closed(self):
        for key, value in (('job_id', 'other'), ('total_frames', 96),
                           ('body_offset_frames', 1), ('fps', True)):
            old = self.plan[key]
            self.plan[key] = value
            self.plan.pop('music_plan_sha256')
            self.plan['music_plan_sha256'] = digest(self.plan)
            self.refresh()
            with self.subTest(key=key), self.assertRaises(audit.JobCompletionAuditError):
                self.check()
            self.plan[key] = old
        self.plan.pop('music_plan_sha256')
        self.plan['music_plan_sha256'] = digest(self.plan)
        self.refresh()
        self.publish('qa-report.json', json.dumps({'background_music': False}).encode())
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()
        self.refresh()
        self.probe = None
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()

    def test_preview_qa_music_sign_alone_is_not_silent_fallback(self):
        empty = self.root / 'otherwise-empty'
        qa = empty / '11-preview/qa-report.json'
        qa.parent.mkdir(parents=True)
        qa.write_text('{"background_music":true}')
        with self.assertRaises(audit.JobCompletionAuditError):
            audit._music_evidence(self.root, empty, {'artifacts': {}}, {}, None)

    def test_audio_clock_not_video_clock_alone(self):
        self.probe['audio_duration_seconds'] = 1
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()

    def test_resigned_options_and_nested_types_rejected(self):
        original = copy.deepcopy(self.plan)
        invalid = [None, [], {**original, 'options': {}},
                   {**original, 'options': {**original['options'], 'material_id': 'wrong'}},
                   {**original, 'options': {**original['options'], 'source': ''}},
                   {**original, 'options': {**original['options'], 'selection':
                       {'start_frame': 0, 'end_frame': 8, 'crossfade_frames': 5}}},
                   {**original, 'options': {**original['options'], 'mix':
                       {**original['options']['mix'], 'music_gain_db': True}}},
                   {**original, 'options': {**original['options'], 'mix':
                       {**original['options']['mix'], 'duck_ratio': 21}}}]
        for value in invalid:
            if isinstance(value, dict):
                value.pop('music_plan_sha256', None)
                value['music_plan_sha256'] = digest(value)
            self.music['plan'] = value
            self.refresh()
            with self.subTest(value=value), self.assertRaises(audit.JobCompletionAuditError):
                self.check()
        self.music['plan'] = original
        self.music['voice_sha256'] = 'a' * 64
        self.refresh()
        with self.assertRaises(audit.JobCompletionAuditError):
            self.check()


if __name__ == '__main__':
    unittest.main()

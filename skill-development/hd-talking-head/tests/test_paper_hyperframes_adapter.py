"""Paper native dispatch and frozen renderer boundary; no paid calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave
import hashlib
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
sys.path[:0] = [str(PROJECT), str(SKILL / 'scripts')]
import paper_hyperframes_adapter as paper


def brief():
    return {'schema_version': 2,
            'source_binding': {'aroll_sha256': 'a' * 64, 'segment_id': 'seg-paper', 'start': 0, 'end': 5},
            'composition': {'width': 1080, 'height': 1920, 'fps': 24, 'frames': 120, 'alpha': False},
            'template_request': {'semantic_family': 'parallel_environment_setup', 'information_units': 2,
                                 'numeric_values': [], 'numeric_scale': 'not_applicable'},
            'entry': {'media_ref': 'entry', 'job_path': 'native/index.html', 'scene_path': 'index.html', 'sha256': 'b' * 64},
            'assets': [{'media_ref': 'paper-' + str(i), 'job_path': 'native/assets/' + str(i) + '.png',
                        'scene_path': 'assets/' + str(i) + '.png', 'sha256': 'c' * 64} for i in range(5)],
            'upstream_route': paper.ROUTE,
            'source_pins': {'route': paper.ROUTE, 'sha256': 'd' * 64}}


class PaperNativeTests(unittest.TestCase):
    def test_stdin_startup_and_factory_pin(self):
        result = subprocess.run([sys.executable, '-', '--skill-root', str(SKILL), '--help'],
            input=(SKILL / paper.ENTRY).read_bytes(), cwd='/', capture_output=True,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b'--authoring-request', result.stdout)
        with patch.object(paper, 'SHARED_SHA', 'f' * 64):
            with self.assertRaisesRegex(ValueError, 'Shared HyperFrames runtime changed'):
                paper.create_adapter(PROJECT, sys.executable, lambda *_: b'')

    def test_native_context_only_passes_facts_clock_assets_and_complete_skill(self):
        b = brief()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / 'authorized-paper.png'
            asset.write_bytes(b'only descriptor hashing is under test')
            action = paper.authoring_context(PROJECT, output_directory=root / 'native',
                source_binding=b['source_binding'], composition=b['composition'],
                template_request=b['template_request'], transcript='同时搭建两套测试环境。',
                semantic_goal='表达并行搭建', assets=[asset], speech=None, word_anchors=[],
                authorization={'paid_generation': False}, parent_subtitle_layout=None)
            self.assertEqual(action['action'], 'execute_native_skill')
            self.assertEqual(action['phase'], 'prepare_template_inputs')
            self.assertEqual(action['skill_path'], str(paper.source_root(PROJECT) / 'SKILL.md'))
            self.assertEqual(action['route'], 'Route B')
            self.assertEqual(len(action['read_files']), len(paper.READ_FILES))
            self.assertNotIn('scene', action['requirements'])
            self.assertNotIn('layers', action['requirements'])
            self.assertEqual(action['requirements']['transcript'], '同时搭建两套测试环境。')
            self.assertIsNone(action['requirements']['speech'])
            self.assertEqual(action['requirements']['word_anchors'], [])
            self.assertEqual(action['requirements']['authorization'], {'paid_generation': False})

    def test_parent_speech_requires_actual_audio_anchors_layout_and_existing_authorization(self):
        from edit.hd.tools.subtitles_v2 import subtitle_layout
        b = brief()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / 'authorized-paper.png'
            asset.write_bytes(b'only descriptor hashing is under test')
            audio = root / 'segment.wav'
            with wave.open(str(audio), 'wb') as target:
                target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                target.writeframes(b'\0' * (16000 * 5 * 2))
            zones, placement = subtitle_layout('none', {'presenter_mode': 'hidden'})
            speech = {'path': str(audio), 'sha256': hashlib.sha256(audio.read_bytes()).hexdigest()}
            authorization = {'paid_generation': False, 'source': 'existing parent authorization'}
            args = dict(output_directory=root / 'native', source_binding=b['source_binding'],
                composition=b['composition'], template_request=b['template_request'],
                transcript='同时搭建两套测试环境。', semantic_goal='表达并行搭建', assets=[asset],
                speech=speech, word_anchors=[{'text': '同时', 'start': .1, 'end': 1}],
                authorization=authorization, parent_subtitle_layout={'safe_zones': zones, 'placement': placement})
            action = paper.authoring_context(PROJECT, **args)
            self.assertEqual(action['requirements']['speech'], {**speech, 'path': str(audio.resolve())})
            self.assertEqual(action['requirements']['word_anchors'], args['word_anchors'])
            self.assertEqual(action['requirements']['authorization'], authorization)
            self.assertTrue(action['requirements']['silent'])
            self.assertEqual(action['requirements']['parent_subtitle_layout'], args['parent_subtitle_layout'])
            for change in ({'speech': {**speech, 'sha256': 'f' * 64}},
                           {'speech': {**speech, 'path': str(root / 'missing.wav')}},
                           {'speech': None}, {'word_anchors': []},
                           {'word_anchors': [{'text': '同时', 'start': 4, 'end': 5.1}]},
                           {'word_anchors': [{'text': '同时', 'start': float('nan'), 'end': 1}]},
                           {'parent_subtitle_layout': None},
                           {'composition': {**b['composition'], 'frames': 96},
                            'source_binding': {**b['source_binding'], 'end': 4}},
                           {'authorization': True}, {'authorization': {'paid_generation': True}}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    paper.authoring_context(PROJECT, **{**args, **change})

    def test_paper_accepts_native_asset_count_but_keeps_identity_and_bitmap_gates(self):
        b = brief()
        self.assertEqual(paper.validate_brief(json.dumps(b)), b)
        for mutate in (lambda value: value['assets'].append(value['assets'][0]),
                       lambda value: value['assets'][0].update(job_path='../outside.png'),
                       lambda value: value['composition'].update(alpha=True),
                       lambda value: value.update(assets=[])):
            invalid = copy.deepcopy(b)
            mutate(invalid)
            with self.assertRaises(ValueError):
                paper.validate_brief(json.dumps(invalid))
        b['upstream_route'] = b['source_pins']['route'] = 'hyperframes/chat-message'
        with self.assertRaises(ValueError):
            paper.hf.validate_brief(json.dumps(b))


if __name__ == '__main__':
    unittest.main()

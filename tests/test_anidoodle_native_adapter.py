"""Necessary native boundary checks; no media generation or external services."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _env
import anidoodle_native_adapter as native
from test_motion_native_skill_adapter import brief as motion_brief


def request():
    value = motion_brief('barty-motion-graphics', 'motion-broll')
    value.update(dependency_id='anidoodle', template_id='paper-craft', alpha=True)
    return value


class AnidoodleNativeTests(unittest.TestCase):
    def test_whole_registry_preserves_thirty_two_native_style_identities(self):
        rows = native.load_template_catalog(_env.PROJECT)
        registry = json.loads((_env.PROJECT / 'vendor/anidoodle/skills/anidoodle/engine/styles.gen.json').read_bytes())
        self.assertEqual(len(rows), 32)
        self.assertEqual({r['native_style_id'] for r in rows}, {s['id'] for s in registry})
        self.assertEqual(len({r['candidate_id'] for r in rows}), 32)
        for row in rows:
            self.assertEqual(row['uses'], ['broll', 'aroll_overlay'])
            self.assertEqual(row['native_role'], 'scene')
            for path in row['native_instructions']:
                self.assertTrue((_env.PROJECT / path).is_file(), path)
            self.assertIn('opaque demo', row['summary'])

    def test_approved_clock_meaning_and_options_remain_independent_of_output_alpha(self):
        original = request()
        self.assertTrue(native.validate_brief(json.dumps(original))['alpha'])
        for alter in (lambda v: v['composition'].update(frames=49),
                      lambda v: v.update(canvas_transport='quarter_turn_cw'),
                      lambda v: v.update(native_options=['paper-craft']),
                      lambda v: v.update(semantic_goal='unapproved new meaning'),
                      lambda v: v.update(project_directory='../vendor/anidoodle'),
                      lambda v: v['word_anchors'][0].update(end=999)):
            value = copy.deepcopy(original); alter(value)
            with self.assertRaises(ValueError):
                native.validate_brief(json.dumps(value))

    def test_an_opaque_codec_with_alpha_flag_is_rejected_by_actual_pixels(self):
        with mock.patch.object(native.subprocess, 'check_output', return_value=b'\xff' * (64 * 114)):
            with self.assertRaisesRegex(ValueError, 'opaque full-frame'):
                native.actual_alpha('pretend.mov')
        pixels = bytes([0] * (64 * 114 - 1) + [255])
        with mock.patch.object(native.subprocess, 'check_output', return_value=pixels):
            self.assertEqual(native.actual_alpha('actual.mov')['min_alpha'], 0)

    def test_native_output_command_cannot_switch_to_a_demo_or_external_renderer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); directory = root / 'native-projects/sample'; directory.mkdir(parents=True)
            engine = native.source_root() / 'skills/anidoodle/engine'
            (directory / 'anidoodle-project.json').write_text(json.dumps({'linked': True, 'engine': str(engine), 'film': 'ownFilm'}))
            value = request(); value['project_directory'] = 'native-projects/sample'
            runtime = {'tools': {'node': '/real/node'}}
            argv = ['/real/node', str(engine / 'tools/render.mjs'), 'ownFilm', '--out', 'out/native.webm', '--workers', '1']
            self.assertEqual(native._render_command(root, value, argv, runtime)[2], directory / 'out/native.webm')
            for index, replacement in ((2, 'paperCraft'), (4, '../elsewhere.webm')):
                altered = list(argv); altered[index] = replacement
                with self.assertRaises(ValueError):
                    native._render_command(root, value, altered, runtime)


if __name__ == '__main__':
    unittest.main()

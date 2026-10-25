"""Real pinned HyperFrames runtime regression; no video export or service call."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from edit.hd.tools.overlay_alignment import bind_native_clock, bind_native_slots, _native_events

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / '参考项目/B-roll开源方案/hyperframes'
CHECKER = ROOT / 'skill-development/hd-talking-head/scripts/check_native_overlay_clock.mjs'


class NativeOverlayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def entry(self, name, *, bad_clip=False, old_selector=False, hidden=False):
        directory = self.directory / name
        (directory / 'vendor').mkdir(parents=True)
        shutil.copyfile(SOURCE / 'skills/talking-head-recut/assets/vendor/gsap.min.js', directory / 'vendor/gsap.min.js')
        route = 'hyperframes/before-after-wipe'
        source = (SOURCE / 'registry/components/before-after-wipe/before-after-wipe.html').read_bytes()
        native = bind_native_slots(bind_native_clock(source, route, 4), {
            key: f'<div class="art {key}"><svg width="420" height="160"><rect width="410" height="150" fill="red"/></svg></div>'
            for key in ('before', 'after')})
        (directory / 'native.html').write_bytes(native)
        css = '''.baw-clip{inset:auto!important;left:60px!important;top:70px!important;width:960px!important;height:280px!important}
.baw-chip{top:12px!important;bottom:auto!important;font-size:72px!important;padding:0!important}
.baw-before .baw-chip{left:24px!important;right:auto!important}.baw-after .baw-chip{right:24px!important;left:auto!important}
.art{position:absolute;top:108px;width:420px;height:160px}.art.before{left:20px}.art.after{right:20px}
'''
        if not bad_clip:
            css += '.baw-after{clip-path:inset(0 0 0 calc((100 - var(--baw-split))*1%))!important}'
        if old_selector:
            css += '#root .baw-chip{font-size:72px}'
        if hidden:
            css += '.stage{opacity:0!important}'
        values = {'label_a': '只有提示词', 'label_b': '完整材料', 'wipe_at': .5, 'rest_split': 50, 'exit': 'fade'}
        (directory / 'index.html').write_text('<script src="vendor/gsap.min.js"></script><style>' + css +
            '</style><div class="stage" data-duration="4"><div class="mount" data-composition-id="before-after-wipe" ' +
            'data-composition-src="native.html" data-start="0" data-duration="4" data-track-index="1" data-width="1080" data-height="1920" ' +
            "data-variable-values='" + json.dumps(values, ensure_ascii=False) + "' " +
            'style="position:absolute;width:1080px;height:1920px;top:0;left:0"></div></div>')
        events, _ = _native_events(route, {'data-start': '0', 'data-variable-values': json.dumps(values)}, 24, 4)
        return {'entry_directory': str(directory), 'route': route, 'duration': 4, 'start': 0,
                'events': [{'slot': slot, 'kind': kind, 'text': text, 'time': time} for slot, kind, text, time in events]}

    def run_check(self, entries):
        return subprocess.run([shutil.which('node'), str(CHECKER)],
            input=json.dumps({'project_root': str(ROOT), 'entries': entries}),
            capture_output=True, text=True, timeout=60)

    def test_actual_runtime_authors_each_entry_and_preserves_native_clock(self):
        result = self.run_check([self.entry('first'), self.entry('second')])
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)['entries']
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['authored_root_id'], 'root')
            self.assertAlmostEqual(row['timeline_duration'], 4, places=5)
            self.assertTrue(row['temporary_duration_removed'])
            self.assertEqual(row['visibility_checks'][0]['graphic_count'], 1)

    def test_right_content_with_left_clip_is_rejected(self):
        result = self.run_check([self.entry('bad-clip', bad_clip=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('after text is clipped or hidden', result.stderr)

    def test_old_root_selector_is_rejected(self):
        result = self.run_check([self.entry('old-selector', old_selector=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('host CSS targets rewritten #root', result.stderr)

    def test_hidden_ancestor_does_not_count_as_visible_text(self):
        result = self.run_check([self.entry('hidden', hidden=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('native content is never visible', result.stderr)

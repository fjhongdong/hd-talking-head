"""BB discovery, one-pass matching and approved native handoff; no rendering."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

import _env
import dependency_preflight
import motion_native_skill_adapter as native
import motion_native_runtime as runtime
import run_stage
from test_motion_native_skill_adapter import brief
from edit.hd.tools import broll_skill_selection as selection, motion_capabilities as motion
from edit.hd.tools import motion_match_cache as cache, visual_confirmation as confirmation
from edit.hd.tools.dependency_contracts import output_alpha

ROOT = _env.PROJECT
STYLES = set('ascii bauhaus blueprint chat collage cutout dossier filmroom grain ink isometric launch lumen manga map mystery newsreel op origami parable pixel pop riso shadow storybook swiss tapestry toy3d trailer whiteboard'.split())


class BBVideoIntegrationTests(unittest.TestCase):
    def test_thirty_styles_are_one_channel_and_only_opaque_broll(self):
        catalog = motion.load_catalog(ROOT)
        rows = [row for row in catalog if row['skill_id'] == 'bb-video']
        self.assertEqual({r['template_id'] for r in rows}, {'bb-video/' + s for s in STYLES})
        self.assertEqual(len(rows), 30)
        self.assertEqual({selection.canonical_identity(r)[0] for r in rows}, {'bb-video'})
        self.assertEqual(len({selection.canonical_identity(r) for r in rows}), 30)
        for row in rows:
            self.assertEqual(row['role'], 'native')
            self.assertEqual(row['capability']['uses'], ['broll'])
            self.assertFalse(output_alpha('code_generated', 'bb-video', 'aroll_with_overlay', 'annotation'))
        self.assertFalse(any(r['skill_id'] == 'bb-video' for r in motion.overlay_candidates(ROOT)))
        by_style = {r['template_id'].split('/')[-1]: r for r in rows}
        self.assertIsNotNone(selection.timing_failure(by_style['parable'], {'segment_id': 's', 'start': 0, 'end': 5}))
        self.assertIsNone(selection.timing_failure(by_style['storybook'], {'segment_id': 's', 'start': 0, 'end': 5}))
        templates = native.load_template_catalog(ROOT, dependency_id='bb-video')
        for template in templates:
            for path in [template['skill_path'], template['native_source'], template['native_runtime'],
                         template['native_starter'], *template['native_starters'], *template['render_scripts'].values()]:
                self.assertTrue((ROOT / path).exists(), path)

    def test_full_matches_are_cached_once_and_overlay_pool_excludes_bb(self):
        director = {'segments': []}
        treatment = {'semantic_lists': {'overlay': [], 'broll': []}, 'motion_queries': []}
        for index, use in enumerate(('overlay', 'broll')):
            sid = 's' + str(index)
            director['segments'].append({'segment_id': sid, 'visual_strategy': {
                'composition': {'family': 'aroll_with_overlay' if use == 'overlay' else 'single_full_frame'},
                'components': [{'component_id': 'c', 'kind': 'code_generated',
                                'layer_role': 'annotation' if use == 'overlay' else 'base'}]}})
            treatment['semantic_lists'][use].append({'row_id': 'r' + str(index), 'start_word': index,
                'end_word': index + 1, 'quote': '任务分工后汇合', 'semantic': '任务分工后汇合',
                'visual_task': '展示团队分工', 'components': [{'segment_id': sid, 'component_id': 'c'}]})
            treatment['motion_queries'].append({'segment_id': sid, 'component_id': 'c', 'tags': ['分工', '汇合']})
        first = cache.match_once(ROOT, director, treatment)
        broll = first['motion_matches']['r1']['matches']
        self.assertEqual(sum(m['candidate_id'].startswith('bb-video:') for m in broll), 30)
        self.assertFalse(any(m['candidate_id'].startswith('bb-video:')
                             for m in first['motion_matches']['r0']['matches']))
        with mock.patch.object(motion, 'search_capabilities', side_effect=AssertionError('must reuse matching')):
            self.assertEqual(cache.match_once(ROOT, director, first), first)
            cache.validate_matches(ROOT, director, first)
        altered = copy.deepcopy(first)
        entry = altered['motion_matches']['r1']
        entry['matches'] = [m for m in entry['matches'] if m['candidate_id'] != 'bb-video:bb-video/storybook']
        entry['matches_sha256'] = motion.contract_artifacts.sha256_json(entry['matches'])
        with self.assertRaises(ValueError):
            cache.validate_matches(ROOT, director, altered)

    def test_stage_dispatch_preserves_source_clock_and_full_native_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = brief('bb-video', 'storybook')
            request['native_options'] = ['explainer']
            with wave.open(str(root / 'voice.wav'), 'wb') as voice:
                voice.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                voice.writeframes(b'\0\0' * 32000)
            request['speech'] = native.descriptor(root, root / 'voice.wav')
            path = root / 'native-inputs/brief.json'
            path.parent.mkdir()
            path.write_text(json.dumps(request))
            binding = {'dependency_id': 'bb-video', 'template_id': 'bb-video/storybook',
                       'brief_sha256': native.sha(path)}
            component = {'component_id': 'c', 'brief': request['task_source']['component_brief']}
            director = {'segments': [{'segment_id': 'seg-001', 'bindings': {'c': binding},
                'visual_strategy': {'mode': 'single', 'composition': {'family': 'single_full_frame', 'presenter_mode': 'hidden'}, 'components': [component]}}]}
            task = request['task_source']
            treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'c', 'brief_path': 'native-inputs/brief.json'}],
                'semantic_lists': {'broll': [{'row_id': task['semantic_row_id'], 'quote': task['quote'],
                    'semantic': task['semantic'], 'components': [{'segment_id': 'seg-001', 'component_id': 'c'}]}]},
                'skill_selection': {'beats': [{'segment_id': 'seg-001', 'component_id': 'c',
                    'semantic_row_id': task['semantic_row_id'], 'required_change': task['required_change'],
                    'component_brief': task['component_brief']}]}}
            job = SimpleNamespace(job_dir=root, job_id=request['job_id'])
            with mock.patch.object(run_stage, '_module', return_value=native), \
                 mock.patch.object(runtime, 'check', return_value={'renderer_version': runtime.renderer_version('bb-video')}):
                action, = run_stage.pending_native_actions(job, director, treatment)
                self.assertEqual(action['action'], 'execute_native_skill')
                self.assertEqual(action['source_binding'], request['source_binding'])
                self.assertEqual(action['native_options'], ['explainer'])
                self.assertTrue(action['skill_path'].endswith('vendor/bb-video/skills/bb-video/SKILL.md'))
                self.assertEqual(action['native_template']['native_runtime'],
                                 'vendor/bb-video/skills/bb-video/promo/runtime/storybook.js')
                self.assertEqual(confirmation.native_candidate_id('bb-video', request,
                    director['segments'][0], 'c'), 'bb-video:bb-video/storybook')
                binding['brief_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'brief changed'):
                    run_stage.pending_native_actions(job, director, treatment)

    def test_preflight_does_not_require_npm_for_bb(self):
        manifest = json.loads((ROOT / 'references/dependency-manifest.json').read_bytes())
        minimal = {'schema_version': 1, 'dependencies': [r for r in manifest['dependencies']
                   if r['id'] in {'node-runtime', 'npm', 'bb-video'}]}
        binding = {'component_kind': 'code_generated', 'dependency_id': 'bb-video',
                   'entrypoint': native.ENTRY, 'producer_version': native.VERSION,
                   'executor': 'reference_adapter', 'primary_renderer': 'HTMLCanvas'}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'manifest.json'; path.write_text(json.dumps(minimal))
            with mock.patch.object(dependency_preflight, '_job_report_identity', return_value={'job_context': None}), \
                 mock.patch.object(dependency_preflight, '_load_recipe_bindings', return_value=[binding]), \
                 mock.patch.object(dependency_preflight, '_reviewed_native_dependencies', return_value=set()), \
                 mock.patch.object(dependency_preflight, '_check_command', side_effect=lambda *_: {'status': 'missing'}), \
                 mock.patch.object(dependency_preflight, '_check_binding_probe', return_value={'status': 'bound'}):
                report = dependency_preflight.build_report(path, ROOT, ROOT, [])
            rows = {r['id']: r for r in report['dependencies']}
            self.assertTrue(rows['node-runtime']['required'])
            self.assertFalse(rows['npm']['required'])
            self.assertTrue(rows['bb-video']['required'])

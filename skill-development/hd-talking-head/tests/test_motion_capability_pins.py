"""Cross-package guard: the pinned capability index must match skill sources on disk."""

from __future__ import annotations

import copy
from contextlib import ExitStack
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

try:
    from edit.hd.tools import motion_capabilities
except ImportError:
    motion_capabilities = None


@unittest.skipUnless(motion_capabilities is not None, "edit.hd runtime is unavailable")
class MotionCapabilityPinTests(unittest.TestCase):
    def test_pinned_capability_sources_match_disk(self):
        profiles = motion_capabilities.load_profiles(PROJECT)
        self.assertEqual(set(profiles), {row['candidate_id'] for row in motion_capabilities.load_catalog(PROJECT)})
        for candidate_id in (
            "adu-motion-video:adu-motion-video/native-compare",
            "hypit-native-chat:hypit/native-plan-change-chat",
            "wise-motion:wise-motion/orbit-tracking-component",
        ):
            self.assertIn(candidate_id, profiles)

    def test_unconnected_and_historical_candidates_are_refused(self):
        profiles = {}
        for cid in ('unconnected:example', 'history:example'):
            profile = {'uses': ['broll'], 'capability_type': 'historical' if cid.startswith('history:') else 'native_component',
                       'reviewed_version': 'source'}
            profiles[cid] = profile
            candidate = {"candidate_id": cid, "role": "broll",
                         "producer_version": profile["reviewed_version"]}
            with self.assertRaisesRegex(ValueError, "not reviewed"):
                motion_capabilities.describe_candidates(PROJECT, [candidate], use="broll", profiles=profiles)


class VisualRetrievalTests(unittest.TestCase):
    def check(self, queries):
        """Exercise tag retrieval while isolating already-tested native inputs."""
        from edit.hd.tools import motion_match_cache, overlay_selection
        profile = {'title': '逐项通知', 'uses': ['aroll_overlay'],
                   'content_scope': {'mode': 'fixed_action', 'evidence_ref': 'fixture'},
                   'tags': {name: [] for name in motion_capabilities.TAG_FIELDS}}
        profile['tags']['actions'] = ['层叠出现']
        profile['tags']['relations'] = ['并列要点']
        catalog = [{'candidate_id': 'overlay:notification-stack', 'status': 'supported',
                    'role': 'overlay', 'skill_id': 'overlay', 'capability': profile}]
        draft = {'segments': [{'segment_id': 'seg-1', 'start': 0.0, 'end': 3.0,
            'visual_intent': {'statement': '并列说明'},
            'visual_strategy': {'mode': 'none', 'composition': {'family': 'aroll_with_overlay'},
                                'components': [{'component_id': 'overlay', 'kind': 'code_generated', 'layer_role': 'annotation', 'brief': '并列说明'}]},
            'bindings': {'overlay': {}}}]}
        treatment = {'motion_queries': queries, 'semantic_assessments': [],
                     'semantic_lists': {'overlay': [{'row_id': 'row-1', 'start_word': 0, 'end_word': 1,
                         'quote': '先摆出三项待办', 'semantic': '并列要点', 'visual_task': '并列说明',
                         'components': [{'segment_id': 'seg-1', 'component_id': 'overlay'}]}], 'broll': []},
                     'skill_selection': {'schema_version': 1, 'beats': [], 'assignments': [], 'overlay_beats': []}}
        patches = (
            mock.patch.object(motion_capabilities, 'load_catalog', return_value=catalog),
            mock.patch.object(motion_capabilities, '_approved_speech', return_value=[{'text': '先摆出三项待办', 'start': 0.0, 'end': 3.0}]),
            mock.patch.object(motion_capabilities, 'validate_overlay_capability'),
            mock.patch.object(motion_capabilities, '_bound_brief', return_value={'upstream_route': 'hyperframes/notification-stack'}),
            mock.patch.object(motion_capabilities, '_semantic_assessment', return_value={'status': 'pass'}),
            mock.patch.object(motion_capabilities, '_native_input_check', return_value={'status': 'pass'}),
            mock.patch('edit.hd.tools.broll_skill_selection.validate_selection', return_value={'assignments': []}),
            mock.patch('edit.hd.tools.overlay_selection._route', return_value='notification-stack'),
            mock.patch('edit.hd.tools.overlay_selection.validate_selection', return_value=[{}]),
        )
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            try:
                treatment = motion_match_cache.match_once(PROJECT, draft, treatment)
            except ValueError:
                return {'status': 'fail'}
            cached = motion_match_cache.validate_matches(PROJECT, draft, treatment)
            item = cached[('seg-1', 'overlay')]
            chosen = 'overlay:' + overlay_selection._route(draft['segments'][0]['bindings']['overlay'])
            treatment['skill_selection']['overlay_beats'] = [{
                'segment_id': 'seg-1', 'component_id': 'overlay', 'semantic_row_id': item['row_id'],
                'start': 0.0, 'end': 3.0, 'transcript': item['semantic']['quote'],
                'semantic_goal': '并列说明', 'required_change': '并列说明', 'intent_statement': '并列说明',
                'component_brief': '并列说明', 'binding_snapshot': {},
                'candidates': [{'candidate_id': m['candidate']['candidate_id'],
                                'fit': 'preferred' if m['candidate']['candidate_id'] == chosen else 'equivalent',
                                'reason': '测试中的完整原生候选评审', 'visual_pattern': 'parallel-list',
                                'design_plan': {'composition': '并列主体在同一视觉范围。',
                                                'typography': '主副字级明确。',
                                                'finish': '细线平面图形保持完整。',
                                                'focus': '当前项目累积时保持其他项。'}}
                               for m in item['matches']],
                'single_source_review': {'decision': 'keep', 'reason': '保留缓存中的原生组件。'}
            }]
            motion_match_cache.validate_reviews(PROJECT, draft, treatment)
            return motion_capabilities.check_offline_plan(PROJECT, draft, treatment)

    def test_overlay_uses_semantic_tags_to_recall_actual_template(self):
        query = {'segment_id': 'seg-1', 'component_id': 'overlay', 'tags': ['并列要点', '层叠出现']}
        result = self.check([query])
        self.assertEqual(result['status'], 'pass', result)
        self.assertEqual(result['checks'][0]['selected'], 'overlay:notification-stack')
        self.assertEqual(result['checks'][0]['query_tags'], query['tags'])
        self.assertEqual(result['spoken_segments']['seg-1'], '先摆出三项待办')
        self.assertFalse(result['checks'][0]['retrieval']['has_motion_basis'])

    def test_missing_duplicate_or_unrelated_tags_cannot_approve_plan(self):
        query = {'segment_id': 'seg-1', 'component_id': 'overlay', 'tags': ['并列要点']}
        for queries in ([], [query, copy.deepcopy(query)],
                        [query | {'tags': ['科技', '浅暖色']}], [query, 'invalid']):
            with self.subTest(queries=queries):
                self.assertEqual(self.check(queries)['status'], 'fail')


if __name__ == "__main__":
    unittest.main()

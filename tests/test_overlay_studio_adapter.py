"""Regression checks for the native seconds contract and speech-event handoff."""
import copy
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from overlay_studio_adapter import ClockConflict, validate_input_clock, validate_brief, validate_parent_layout, validate_visible_bounds


class PinBoardContractTest(unittest.TestCase):
    def setUp(self):
        self.brief = {
            "schema_version": 1,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-001", "start": 10, "end": 10 + 172 / 24},
            "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 172, "alpha": True},
            "doc": {"version": 1, "theme": "light", "font": "PingFang SC", "glow": False, "breath": False,
                    "cards": [{"id": "card-1", "kind": "pin-board", "start": 0, "end": 172 / 24,
                               "params": {"theme": "light", "position": "top-left", "title": "", "subtitle": "",
                                          "items": "记得经过|却不会举证", "times": "3.458333333|5.791666667",
                                          "accent": "orange", "scale": 2, "speed": 1, "offsetX": 0, "offsetY": 0, "sfx": "none"}}]},
            "layout": {"crop": {"x": 64, "y": 64, "width": 1000, "height": 480},
                       "placement": {"x": 40, "y": 57, "width": 750, "height": 360}},
            "parent_safe_zone": {"left": 40, "top": 64, "right": 40, "bottom": 320},
            "template_request": {"semantic_family": "cumulative_points", "information_units": 2,
                                 "numeric_values": [], "numeric_scale": "not_applicable"},
            "execution_mode": "native_export", "assets": [],
            "upstream": {"source_revision": "e35e1aff9dae3b3addc21f68f3bcd51f95bdc1a8", "runtime_identity": "b" * 64}}

    def test_real_native_shape_accepts_fractional_seconds_and_absent_optional_fields(self):
        self.assertEqual(validate_brief(self.brief), self.brief)

    def test_native_binding_uses_current_brief_without_historical_sample(self):
        import json
        from types import SimpleNamespace
        import overlay_studio_adapter as native
        adapter = SimpleNamespace(dependency_id=native.DEPENDENCY_ID,
            entrypoint=native.ENTRY, entrypoint_sha256=native.sha(SKILL / native.ENTRY),
            primary_renderer=native.RENDERER, launcher=Path(sys.executable))
        binding = native.create_binding(adapter, json.dumps(self.brief).encode())
        self.assertEqual(binding['template_origin'], 'custom_fallback')
        self.assertNotIn('sample_sha256', binding)
        self.assertEqual(binding['invocation_record']['status'], 'planned')
        self.assertIsNone(binding['invocation_record']['exit_code'])
        self.assertEqual(binding['invocation_record']['template_request'], self.brief['template_request'])

    def test_rejects_frames_in_native_seconds_field(self):
        self.brief["doc"]["cards"][0]["end"] = 172
        with self.assertRaises(ValueError):
            validate_brief(self.brief)

    def test_28_frame_choice_keeps_twelve_reading_frames_after_last_landing(self):
        brief = copy.deepcopy(self.brief)
        brief['source_binding'].update(start=436 / 24, end=464 / 24)
        brief['composition']['frames'] = 28
        card = brief['doc']['cards'][0]
        card['end'] = 28 / 24
        card['params'].update(items='使用|不使用', times='0.16|0.24')
        with self.assertRaises(ClockConflict):
            validate_input_clock(brief)
        brief['source_binding']['end'] = 436 / 24 + 36 / 24
        brief['composition']['frames'] = 36
        card['end'] = 36 / 24
        with self.assertRaises(ClockConflict):
            validate_input_clock(brief)
        brief['source_binding']['end'] = 436 / 24 + 37 / 24
        brief['composition']['frames'] = 37
        card['end'] = 37 / 24
        self.assertEqual(validate_input_clock(brief), brief)

    def test_real_142_frame_clock_conflict_is_separate_from_runtime_and_format(self):
        brief = copy.deepcopy(self.brief)
        brief['source_binding'].update(start=4.625, end=4.625 + 142 / 24)
        brief['composition']['frames'] = 142
        card = brief['doc']['cards'][0]
        card['end'] = 142 / 24
        card['params'].update(items='快递|外卖|面试|家里', times='3.24|3.88|4.5|5.34')
        brief['template_request']['information_units'] = 4
        brief['upstream']['runtime_identity'] = None
        with self.assertRaises(ClockConflict):
            validate_input_clock(brief)
        for times in ('3.24|3.88|4.5', '3.24|4.5|3.88|5.34', '3.24|3.88|4.5|NaN'):
            broken = copy.deepcopy(brief)
            broken['doc']['cards'][0]['params']['times'] = times
            with self.subTest(times=times), self.assertRaises(ValueError) as error:
                validate_input_clock(broken)
            self.assertNotIsInstance(error.exception, ClockConflict)
        brief['source_binding']['end'] = 4.625 + 148 / 24
        brief['composition']['frames'] = 148
        card['end'] = 148 / 24
        with self.assertRaises(ClockConflict):
            validate_input_clock(brief)
        brief['source_binding']['end'] = 4.625 + 160 / 24
        brief['composition']['frames'] = 160
        card['end'] = 160 / 24
        self.assertEqual(validate_input_clock(brief), brief)
        with self.assertRaisesRegex(ValueError, 'upstream identity'):
            validate_brief(brief)

    def test_rejects_silent_native_fallback_and_unknown_parameters(self):
        for key, value in (("times", "3.458333333"), ("fontSize", 64)):
            altered = copy.deepcopy(self.brief)
            altered["doc"]["cards"][0]["params"][key] = value
            with self.assertRaises(ValueError):
                validate_brief(altered)

    def test_parent_layout_snapshot_must_match_actual_component(self):
        component = {"artifact_contract": {"width": 1080, "height": 1920},
                     "render_window": {"safe_zone": copy.deepcopy(self.brief["parent_safe_zone"])}}
        validate_parent_layout(self.brief, component)
        component["render_window"]["safe_zone"]["top"] = 65
        with self.assertRaisesRegex(ValueError, "approved parent"):
            validate_parent_layout(self.brief, component)
        component["render_window"]["safe_zone"]["top"] = 64
        component["artifact_contract"]["height"] = 1080
        with self.assertRaisesRegex(ValueError, "canvas"):
            validate_parent_layout(self.brief, component)
        del self.brief["parent_safe_zone"]
        with self.assertRaises(ValueError):
            validate_brief(self.brief)

    def test_prepared_pinboard_layout_does_not_compile_unprepared_sibling(self):
        import json, tempfile
        from types import SimpleNamespace
        from edit.hd.tests.test_visual_direction import draft_segment
        from edit.hd.tools.visual_strategy import validate_visual_strategy
        import overlay_studio_adapter as native
        import run_stage
        segment = draft_segment(('code_generated', 'code_generated'),
                                start=10, end=10 + 172 / 24)
        strategy = segment['visual_strategy']
        strategy['mode'] = 'none'
        strategy['composition'] = {'family': 'aroll_with_overlay', 'presenter_mode': 'full_frame',
            'reading_order': ['component-1', 'component-2'], 'component_dependencies': []}
        for component in strategy['components']:
            component.update(layer_role='annotation', layout_slot='annotation')
        validate_visual_strategy(segment['visual_intent'], strategy)
        adapter = SimpleNamespace(dependency_id=native.DEPENDENCY_ID, entrypoint=native.ENTRY,
            entrypoint_sha256=native.sha(SKILL / native.ENTRY), primary_renderer=native.RENDERER,
            launcher=Path(sys.executable))
        payload = json.dumps(self.brief).encode()
        segment['bindings']['component-2'] = native.create_binding(adapter, payload)
        segment['bindings']['component-1'] = {'producer_type': 'dependency', 'dependency_id': 'barty-motion-graphics'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); (root / 'pinboard.json').write_bytes(payload)
            treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'component-2', 'brief_path': 'pinboard.json'}]}
            run_stage._validate_prepared_native_inputs(SimpleNamespace(job_dir=root), SKILL,
                {'segments': [segment]}, treatment, planned={('seg-001', 'component-1')})
            self.assertFalse((root / 'native-projects').exists())

    def test_complete_motion_must_fit_parent_before_encoding(self):
        native_bounds = (88, 79, 717, 525)
        self.assertEqual(validate_visible_bounds(native_bounds, self.brief), (56, 66, 532, 405))
        self.brief["layout"]["placement"] = {"x": 0, "y": 0, "width": 1000, "height": 480}
        with self.assertRaisesRegex(ValueError, "exceeds parent safe rectangle"):
            validate_visible_bounds(native_bounds, self.brief)

    def test_alignment_consumes_treatment_events_without_duplicate_brief_fields(self):
        from edit.hd.tools import pinboard_alignment
        words = [{"text": "记录", "start": 13.45, "end": 13.7}, {"text": "不会", "start": 15.78, "end": 16}]
        events = [{"slot": i, "kind": "pin_drop", "text": text,
                   "anchor": {"index": i, "text": words[i]["text"]}, "basis": "current_clause"}
                  for i, text in enumerate(("记得经过", "却不会举证"))]
        segment = {**self.brief["source_binding"], "visible_text": ["记得经过", "却不会举证"]}
        cuts = [{"source_start": 0, "source_end": 20, "timeline_start": 0}]
        checked = pinboard_alignment.validate_brief(self.brief, segment=segment, words=words, cuts=cuts, events=events)
        self.assertEqual(len(checked), 2)
        self.assertAlmostEqual(checked[1]["effective_time"], 15.791666667)
        with self.assertRaises(ValueError):
            pinboard_alignment.validate_brief(self.brief, segment=segment, words=words, cuts=cuts, events=events[:1])


if __name__ == "__main__":
    unittest.main()

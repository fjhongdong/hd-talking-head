import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edit.hd.tools.overlay_alignment import validate_treatment, _native_events, bind_native_clock, bind_native_slots, _native_clock
from edit.hd.tools.overlay_selection import validate_selection

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "vendor/hyperframes/registry/components"


class OverlayAlignmentTest(unittest.TestCase):
    def test_missing_overlay_declaration_can_only_realize_the_frozen_route(self):
        import copy
        from edit.hd.tools import visual_confirmation as confirmation
        frozen = {'segments': [{'segment_id': 'seg-004', 'visible_text': [],
            'visual_strategy': {'composition': {'family': 'aroll_with_overlay'}},
            'bindings': {'visual': {'producer_type': 'dependency', 'dependency_id': 'overlay-studio-native',
                'template_id': 'overlay-studio/pin-board'}}}]}
        row = {'segment_id': 'seg-004', 'component_id': 'visual', 'intent_relation': 'parallel',
            'native_route': 'pin-board', 'visible_action': 'cumulative_pin_drop',
            'visual_structure': 'pin-board', 'selection_reason': 'approved parallel contract names'}
        original, realized = {}, {'overlay_selection': [row]}
        proposal = {'inputs': {'director': 'director', 'treatment': 'treatment'}}
        with patch.object(confirmation, '_exact', side_effect=lambda root, value: value), \
             patch.object(confirmation, '_read', side_effect=lambda path: frozen if path == 'director' else original), \
             patch.object(confirmation, '_validate_authorized_native_inputs'), \
             patch('edit.hd.tools.motion_capabilities.overlay_candidates', return_value=[]), \
             patch('edit.hd.tools.motion_capabilities.validate_overlay_capability'):
            confirmation._validate_draft_against_source(Path('/unused'), proposal, frozen, realized)
            with self.assertRaisesRegex(ValueError, 'binding structure'):
                confirmation._validate_draft_against_source(Path('/unused'), proposal, frozen,
                    {'overlay_selection': [{**row, 'native_route': 'toggle-flip'}]})
            original['overlay_selection'] = [copy.deepcopy(row)]
            with self.assertRaisesRegex(ValueError, 'overlay_selection'):
                confirmation._validate_draft_against_source(Path('/unused'), proposal, frozen,
                    {'overlay_selection': [{**row, 'selection_reason': 'changed explicit approval'}]})

    def test_fresh_native_labels_use_only_spoken_words_and_keep_comparison_source(self):
        from edit.hd.tools.pinboard_alignment import checked_labels
        from edit.hd.tools.overlay_alignment import validate_native_events
        words = [{"text": text, "start": i, "end": i + .5}
                 for i, text in enumerate(("劳动合同", "竞业协议", "股权协议", "未入本镜"))]
        segment = {"segment_id": "seg-004", "start": 0, "end": 3, "visible_text": []}
        cuts = [{"source_start": 0, "source_end": 4, "timeline_start": 0}]
        labels = [word['text'] for word in words[:3]]
        self.assertEqual(checked_labels(labels, segment=segment, words=words, cuts=cuts, allow_spoken=True), labels)
        for invalid in (["虚构协议"], ["未入本镜"]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'approved speech'):
                checked_labels(invalid, segment=segment, words=words, cuts=cuts, allow_spoken=True)
        with self.assertRaisesRegex(ValueError, 'visible text'):
            checked_labels(labels, segment={**segment, 'visible_text': ['明确批准文案']},
                           words=words, cuts=cuts, allow_spoken=True)
        with self.assertRaisesRegex(ValueError, 'visible text'):
            checked_labels(labels, segment=segment, words=words, cuts=cuts)

        route = 'hyperframes/before-after-wipe'
        source = (SOURCE_ROOT / 'before-after-wipe/before-after-wipe.html').read_bytes()
        clock = bind_native_clock(source, route, 4)
        slot_labels = {'before': '劳动合同', 'after': '竞业协议'}
        contents = {key: '<svg viewBox="0 0 500 200"><text x="30" y="100" font-size="64">' + value + '</text></svg>'
                    for key, value in slot_labels.items()}
        filled = bind_native_slots(clock, contents, labels=slot_labels)
        self.assertEqual(_native_clock(source, filled, route, 4, labels=slot_labels), 4)
        with self.assertRaisesRegex(ValueError, 'checked'):
            bind_native_slots(clock, contents)
        with self.assertRaisesRegex(ValueError, 'differs'):
            bind_native_slots(clock, {**contents, 'after': contents['after'].replace('竞业协议', '虚构协议')}, labels=slot_labels)
        with self.assertRaisesRegex(ValueError, 'static markup'):
            bind_native_slots(clock, {**contents, 'after': '<script>竞业协议</script>'}, labels=slot_labels)
        with self.assertRaisesRegex(ValueError, 'duration parameters'):
            _native_clock(source, filled.replace(b'WIPE_DURATION_BASE = 1.05', b'WIPE_DURATION_BASE = 0.5'), route, 4, labels=slot_labels)
        mount = {'data-variable-values': json.dumps({'label_a': '', 'label_b': '', 'wipe_at': 1, 'exit': 'none'})}
        actual, _ = _native_events(route, mount, 24, 4, comparison_labels=slot_labels)
        events = [{'slot': slot, 'kind': kind, 'text': text,
                   'anchor': {'index': slot, 'text': words[slot]['text']},
                   'basis': 'recap' if kind == 'wipe_land' else 'current_clause'}
                  for slot, kind, text, _ in actual]
        checked = validate_native_events(actual, segment={**segment, 'end': 4}, words=words,
            cuts=cuts, events=events, allow_spoken_labels=True)
        self.assertEqual(len(checked), 3)

    def test_grid_clock_reads_native_settle_and_keeps_parent_hold_separate(self):
        from edit.hd.tools.overlay_alignment import _grid_tile_seconds, validate_grid_clock, GridClockConflict
        source = (SOURCE_ROOT / "grid-card-assemble/grid-card-assemble.html").read_bytes()
        self.assertEqual(_grid_tile_seconds(source, 142 / 24), 0.65)
        self.assertEqual(_grid_tile_seconds(source, 0.3), 0.2)
        self.assertEqual(_grid_tile_seconds(source.replace(b'TILE_BASE = 0.65', b'TILE_BASE = 0.9'), 6), 0.9)
        cue = [(0, "reveal", "家里", 5.34)]
        with self.assertRaises(GridClockConflict):
            validate_grid_clock(cue, source, 142 / 24)
        # Native landing alone fits, but the parent's 12 reading frames do not.
        with self.assertRaises(GridClockConflict):
            validate_grid_clock(cue, source, 6.0)
        validate_grid_clock(cue, source, 156 / 24)
        with self.assertRaises(ValueError) as error:
            validate_grid_clock(cue, source.replace(b'avail - BASE_START', b'avail'), 6.5)
        self.assertNotIsInstance(error.exception, GridClockConflict)

    def test_comparison_slots_preserve_native_motion_and_anchor_both_states(self):
        route = "hyperframes/before-after-wipe"
        source = (SOURCE_ROOT / "before-after-wipe/before-after-wipe.html").read_bytes()
        clock = bind_native_clock(source, route, 10.75)
        content = {"before": '<div class="before-art"><svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg></div>',
                   "after": '<div class="after-art"><svg viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8"/></svg></div>'}
        filled = bind_native_slots(clock, content)
        self.assertEqual(_native_clock(source, filled, route, 10.75), 10.75)
        with self.assertRaisesRegex(ValueError, "duration parameters"):
            _native_clock(source, filled.replace(b'WIPE_DURATION_BASE = 1.05', b'WIPE_DURATION_BASE = 0.5'), route, 10.75)
        with self.assertRaisesRegex(ValueError, "static markup"):
            bind_native_slots(clock, {**content, "after": '<script>alert(1)</script>'})
        mount = {"data-start": "0.375", "data-variable-values": json.dumps({
            "label_a": "不能只诉苦", "label_b": "要拿出凭证", "wipe_at": 2, "rest_split": 50, "exit": "fade"})}
        events, end = _native_events(route, mount, 24, 10.375)
        self.assertEqual([item[1] for item in events], ["reveal", "wipe_start", "wipe_land"])
        self.assertAlmostEqual(events[1][3], 2.375)
        self.assertAlmostEqual(events[2][3], 3.425)
        self.assertAlmostEqual(end, 10.75)
        with self.assertRaisesRegex(ValueError, "clamped"):
            _native_events(route, mount, 24, 1)
        values = json.loads(mount["data-variable-values"])
        for split in (65, 100):
            with self.subTest(rest_split=split):
                mount["data-variable-values"] = json.dumps({**values, "rest_split": split, "exit": "none"})
                full_events, full_end = _native_events(route, mount, 24, 10.375)
                self.assertEqual(full_events, events)
                self.assertEqual(full_end, end)
        for split in (0, 100.1):
            with self.subTest(rest_split=split), self.assertRaisesRegex(ValueError, "public range"):
                mount["data-variable-values"] = json.dumps({**values, "rest_split": split})
                _native_events(route, mount, 24, 10.375)

    def test_overlay_selection_records_native_action_and_rejects_missing_route(self):
        from edit.hd.tools.motion_capabilities import overlay_candidates
        registered = next(row for row in overlay_candidates(Path(__file__).resolve().parents[3])
                          if row['source_route'] == 'toggle-flip')
        draft = {"segments": [{
            "segment_id": "seg-001",
            "visible_text": ["已提交", "未到账"],
            "visual_intent": {"statement": "状态发生变化"},
            "visual_strategy": {"composition": {"family": "aroll_with_overlay"}},
            "bindings": {"native-visual": {
                "dependency_id": "hyperframes-native-adaptation",
                "template_id": "hyperframes-toggle-flip-portrait-adaptation",
                "entrypoint": registered['entrypoint'],
                "producer_version": registered['producer_version'],
            }},
        }]}
        treatment = {"overlay_selection": [{
            "segment_id": "seg-001", "component_id": "native-visual",
            "intent_relation": "state_change", "native_route": "toggle-flip",
            "visible_action": "state_toggle", "visual_structure": "toggle-rail",
            "selection_reason": "原生开关表达状态变化",
        }]}
        routes = {("seg-001", "native-visual"): "toggle-flip", ("seg-002", "native-visual"): "toggle-flip"}
        rows = validate_selection(draft, treatment, routes)
        self.assertEqual(rows[0]["native_route"], "toggle-flip")
        self.assertEqual(rows[0]["visible_action"], "state_toggle")
        bad = json.loads(json.dumps(draft))
        bad["segments"][0]["bindings"]["native-visual"]["template_id"] = "unknown-route"
        with self.assertRaisesRegex(ValueError, "not supported"):
            validate_selection(bad, treatment, routes)
        with self.assertRaisesRegex(ValueError, "declaration is required"):
            validate_selection(draft, {}, routes)
        with self.assertRaisesRegex(ValueError, "native brief route"):
            validate_selection(draft, treatment, {("seg-001", "native-visual"): "grid-card-assemble"})
        duplicate = json.loads(json.dumps(draft))
        duplicate["segments"].append({**duplicate["segments"][0], "segment_id": "seg-002", "visible_text": ["已完成", "待核对"]})
        repeated = {"overlay_selection": [*treatment["overlay_selection"], {**treatment["overlay_selection"][0], "segment_id": "seg-002", "selection_reason": "第二处同样表达状态切换"}]}
        with self.assertRaisesRegex(ValueError, "repeat_review"):
            validate_selection(duplicate, repeated, routes)
        repeated["repeat_review"] = [{"native_route": "toggle-flip", "visual_structure": "toggle-rail", "reason": "两处均为明确的状态切换，保留原生开关一致性"}]
        rows = validate_selection(duplicate, repeated, routes)
        self.assertTrue(all("repeat_review_reason" in row for row in rows))

    @patch("edit.hd.tools.overlay_alignment._assembled_clocks", side_effect=lambda entries: [{} for _ in entries])
    def test_approved_cut_clock_and_recap(self, _assembly):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            root = workspace / "edit/hd/jobs/current"
            root.mkdir(parents=True)
            stages = {"speech_cleanup": {"status": "completed", "artifacts": []},
                      "edit_structure": {"status": "completed", "artifacts": []}}
            def write(relative, value, stage=None):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
                path.write_bytes(data)
                sha = hashlib.sha256(data).hexdigest()
                if stage:
                    stages[stage]["artifacts"].append({"path": relative, "bytes": len(data), "sha256": sha})
                return sha
            write("05-speech-cleanup/word-transcript.json", {"words": [
                {"start": 10.05, "end": 10.2, "text": "活"},
                {"start": 11.3, "end": 11.5, "text": "核对"}]}, "speech_cleanup")
            write("06-edit-structure/timeline-map.json", {"segments": [
                {"source_start": 10, "source_end": 12, "timeline_start": 0, "timeline_end": 2}]}, "edit_structure")
            ar = write("06-edit-structure/edited-aroll.mp4", b"unchanged approved media", "edit_structure")
            source = (SOURCE_ROOT / "grid-card-assemble/grid-card-assemble.html").read_bytes()
            source_sha = hashlib.sha256(source).hexdigest()
            native_sha = write("native-inputs/native.html", bind_native_clock(source, "hyperframes/grid-card-assemble", 2))
            entry = '<div data-composition-id="grid-card-assemble" data-composition-src="native.html" data-variable-values=\'{"items":"核对","cues":"1.3","exit":"none"}\' data-start="0" data-duration="2"></div>'
            entry_sha = write("native-inputs/index.html", entry.encode())
            brief_sha = write("native-inputs/brief.json", {
                "source_binding": {"aroll_sha256": ar, "segment_id": "seg-001", "start": 0, "end": 2},
                "entry": {"job_path": "native-inputs/index.html", "scene_path": "index.html", "sha256": entry_sha},
                "composition": {"alpha": True, "fps": 24}, "upstream_route": "hyperframes/grid-card-assemble",
                "source_pins": {"sha256": source_sha},
                "assets": [{"scene_path": "native.html", "job_path": "native-inputs/native.html", "sha256": native_sha}]})
            draft = {"segments": [{"segment_id": "seg-001", "start": 0, "end": 2,
                "visual_strategy": {"composition": {"family": "aroll_with_overlay"}},
                "visible_text": ["核对"], "bindings": {"visual": {
                    "dependency_id": "hyperframes-native-adaptation", "brief_sha256": brief_sha}}}]}
            event = {"slot": 0, "kind": "reveal", "text": "核对",
                     "anchor": {"index": 1, "text": "核对"}, "basis": "current_clause"}
            record = {"segment_id": "seg-001", "component_id": "visual",
                      "brief_path": "native-inputs/brief.json", "events": [event]}
            treatment = root / "treatment.json"
            job = SimpleNamespace(root=workspace, job_dir=root, stages=stages)
            write("treatment.json", {})
            with self.assertRaisesRegex(ValueError, "records are required"):
                validate_treatment(job, draft, treatment)
            write("treatment.json", {"overlay_alignment": [record]})
            result = validate_treatment(job, draft, treatment)
            self.assertAlmostEqual(result[0]["events"][0]["anchor_time"], 1.3)
            self.assertEqual({item["scene_path"] for item in _assembly.call_args.args[0][0]["files"]},
                             {"index.html", "native.html"})
            # A future recap cannot be admitted just because it has an anchor.
            event["basis"] = "recap"
            native = entry.replace('"1.3"', '"0.1"')
            entry_sha = write("native-inputs/index.html", native.encode())
            brief = json.loads((root / "native-inputs/brief.json").read_text())
            brief["entry"]["sha256"] = entry_sha
            draft["segments"][0]["bindings"]["visual"]["brief_sha256"] = write("native-inputs/brief.json", brief)
            write("treatment.json", {"overlay_alignment": [record]})
            with self.assertRaisesRegex(ValueError, "has not happened"):
                validate_treatment(job, draft, treatment)

    def test_actual_native_slots_and_cue_clamp(self):
        with self.assertRaisesRegex(ValueError, "clamped"):
            _native_events("hyperframes/notification-stack", {"data-start": "0", "data-duration": "2",
                "data-variable-values": '{"titles":"AI不会要钱","cues":"1.5","exit":"fade"}'}, 24, 2)
        events, exit_time = _native_events("hyperframes/toggle-flip", {"data-start": "0.2",
            "data-duration": "0.7", "data-variable-values": '{"label":"自己核对"}'}, 24, 0.7)
        self.assertAlmostEqual(events[1][3], 0.45)
        self.assertAlmostEqual(exit_time, 0.9)

    def test_native_clock_binding_keeps_the_original_animation(self):
        for name, duration in (("grid-card-assemble", 7.166666666666671),
                               ("notification-stack", 3.291666666666657),
                               ("toggle-flip", 2.068333333333335)):
            source = (SOURCE_ROOT / name / (name + ".html")).read_bytes()
            route = "hyperframes/" + name
            with self.assertRaisesRegex(ValueError, "duration parameters"):
                _native_clock(source, source, route, duration)
            bound = bind_native_clock(source, route, duration)
            self.assertEqual(_native_clock(source, bound, route, duration), duration)
            for kind in ("script", "style"):
                import re
                pattern = rb"<" + kind.encode() + rb"\b[^>]*>.*?</" + kind.encode() + rb">"
                original_blocks = re.findall(pattern, source, re.S)
                bound_blocks = [b for b in re.findall(pattern, bound, re.S)
                                if b"data-hd-native-clock=" not in b]
                self.assertEqual(original_blocks, bound_blocks)
            with self.assertRaisesRegex(ValueError, "duration parameters"):
                _native_clock(source, bound + b" ", route, duration)


if __name__ == "__main__":
    unittest.main()

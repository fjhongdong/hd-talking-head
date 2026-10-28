import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edit.hd.tools.overlay_alignment import validate_treatment, _native_events, bind_native_clock, bind_native_slots, _native_clock
from edit.hd.tools.overlay_selection import validate_selection

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "参考项目/B-roll开源方案/hyperframes/registry/components"


class OverlayAlignmentTest(unittest.TestCase):
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
            stages = {"speech_cleanup": {"status": "approved", "artifacts": []},
                      "edit_structure": {"status": "approved", "artifacts": []}}
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

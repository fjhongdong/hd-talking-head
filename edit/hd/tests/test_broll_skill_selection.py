"""Offline selection smoke; no render, provider call, or historical Job write."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edit.hd.tools import broll_skill_selection as selection, visual_plan

ROOT = Path(__file__).resolve().parents[3]


class BrollSkillSelectionTest(unittest.TestCase):
    def test_native_timing_evidence_reads_existing_adapter_frame_limits(self):
        candidates=selection.discover_candidates(ROOT)
        for source in ('adu-motion-video','hypit-native-chat'):
            row=next(c for c in candidates if c['skill_id']==source)
            self.assertEqual(row['min_duration_seconds'],5)
        rollup = next(c for c in candidates if c['candidate_id'] == 'html-video:html-video/frame-data-rollup')
        adu = next(c for c in candidates if c['skill_id'] == 'adu-motion-video')
        self.assertEqual(rollup['min_duration_seconds'], 3)
        converge = next(c for c in candidates if c['candidate_id'] ==
                        'talkcraft-native-adaptation:template/cards/source-converge.tsx')
        self.assertEqual(converge['min_duration_seconds'], 5.6)
        for row, before, minimum in ((rollup, 71, 72), (adu, 119, 120), (converge, 134, 135)):
            beat = {'segment_id': 'seg-check', 'start': 0, 'end': before / 24}
            self.assertIsNotNone(selection.timing_failure(row, beat))
            beat['end'] = minimum / 24
            self.assertIsNone(selection.timing_failure(row, beat))

    def complete_overlay_cache(self, draft, treatment):
        from edit.hd.tools import motion_match_cache, overlay_selection
        for segment in draft["segments"]:
            segment.setdefault("visual_intent", {"statement": "并列说明"})
            for component in segment["visual_strategy"]["components"]:
                component["layer_role"] = "annotation"
        treatment = motion_match_cache.match_once(ROOT, draft, treatment)
        cached = motion_match_cache.validate_matches(ROOT, draft, treatment)
        beats = []
        for segment in draft["segments"]:
            for component in segment["visual_strategy"]["components"]:
                sid, cid = segment["segment_id"], component["component_id"]
                chosen = "overlay:" + overlay_selection._route(segment["bindings"][cid])
                item = cached[(sid, cid)]
                beats.append({"segment_id": sid, "component_id": cid, "semantic_row_id": item["row_id"],
                    "start": segment["start"], "end": segment["end"], "transcript": item["semantic"]["quote"],
                    "semantic_goal": "explain", "required_change": component["brief"],
                    "intent_statement": segment["visual_intent"]["statement"], "component_brief": component["brief"],
                    "binding_snapshot": copy.deepcopy(segment["bindings"][cid]),
                    "candidates": [{"candidate_id": match["candidate"]["candidate_id"],
                        "fit": "preferred" if match["candidate"]["candidate_id"] == chosen else
                            "equivalent" if match["candidate"]["status"] == "supported" else "needs_adapter",
                        "reason": "测试中的完整原生候选评审", "visual_pattern": "parallel-list"}
                        | {"design_plan": {"composition": "并列主体在同一视觉范围。", "typography": "主副字级明确。",
                                           "finish": "细线平面图形保持完整。", "focus": "当前项目累积时保持其他项。"}}
                        for match in item["matches"]]})
                beats[-1]['single_source_review'] = {'decision': 'keep', 'reason': '完整保留缓存中可用的原生组件。'}
        treatment["skill_selection"]["overlay_beats"] = beats
        treatment["skill_selection"] = selection.assign_skills(ROOT, treatment["skill_selection"])
        return treatment

    def test_cited_semantics_and_native_checks_offline_smoke(self):
        """Synthetic text inputs only: no existing Job, motion or video is used."""
        from edit.hd.tools import motion_capabilities as motion

        catalog = motion.load_catalog(ROOT)
        row = next(item for item in catalog if item["candidate_id"] == "overlay:grid-card-assemble")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(relative, value):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                return motion.contract_artifacts.sha256_file(path)

            words = [{"text": "模型在本地执行。", "start": 0.0, "end": 1.0},
                     {"text": "无需云API，先用手头工具。", "start": 2.0, "end": 4.0},
                     {"text": "之后再判断。", "start": 6.0, "end": 7.0}]
            workflow = {"stages": {}}
            for stage, relative, value in (
                ("speech_cleanup", "05-speech-cleanup/word-transcript.json", {"version": 1, "words": words}),
                ("edit_structure", "06-edit-structure/timeline-map.json", {"segments": [{
                    "source_start": 0, "source_end": 8, "timeline_start": 0, "timeline_end": 8}]}),
            ):
                digest = write(relative, value)
                workflow["stages"][stage] = {"status": "approved", "artifacts": [{
                    "path": relative, "sha256": digest, "bytes": (root / relative).stat().st_size}]}
            write("workflow.json", workflow)
            source = root / "native-inputs/example/index.html"
            source.parent.mkdir(parents=True)
            source.write_text("<div>本地执行 · 无需云API · 先用手头工具</div>", encoding="utf-8")
            brief = {"schema_version": 2, "source_binding": {"aroll_sha256": "a" * 64,
                "segment_id": "seg-smoke", "start": 2, "end": 5},
                "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 72, "alpha": True},
                "template_request": {"semantic_family": "parallel", "information_units": 3,
                    "numeric_values": [], "numeric_scale": "not_applicable"},
                "entry": {"media_ref": "entry", "job_path": "native-inputs/example/index.html",
                    "scene_path": "index.html", "sha256": motion.contract_artifacts.sha256_file(source)},
                "assets": [], "upstream_route": "hyperframes/grid-card-assemble",
                "source_pins": {"route": "hyperframes/grid-card-assemble", "sha256": "b" * 64}}
            relative = "native-inputs/example/brief.json"
            digest = write(relative, brief)
            binding = {key: row[key] for key in ("dependency_id", "entrypoint", "producer_version", "template_id")}
            binding["brief_sha256"] = digest
            segment = {"segment_id": "seg-smoke", "start": 2, "end": 5,
                "visual_strategy": {"mode": "none", "composition": {"family": "aroll_with_overlay"},
                                     "components": [{"component_id": "scene", "kind": "code_generated", "brief": "并列说明"}]},
                "bindings": {"scene": binding}}
            draft = {"segments": [segment]}
            assessment = {"segment_id": "seg-smoke", "component_id": "scene",
                "candidate_id": row["candidate_id"], "verdict": "pass",
                "reason": "三个短标签是摘要而非流程；本地执行来自已说上文，当前原文保留无需这一否定。",
                "transcript_refs": [{"start_word": 1, "end_word": 2,
                    "quote": words[1]["text"], "basis": "current_clause"},
                    {"start_word": 0, "end_word": 1, "quote": words[0]["text"], "basis": "recap"}],
                "content_refs": [{"path": brief["entry"]["job_path"], "sha256": brief["entry"]["sha256"],
                    "quote": "本地执行 · 无需云API · 先用手头工具"}]}
            treatment = {"semantic_lists": {"overlay": [{"row_id": "row-smoke", "start_word": 0, "end_word": 3, "quote": "模型在本地执行。无需云API，先用手头工具。之后再判断。", "semantic": "本地执行", "visual_task": "并列说明", "components": [{"segment_id": "seg-smoke", "component_id": "scene"}]}], "broll": []}, "motion_queries": [{"segment_id": "seg-smoke", "component_id": "scene", "tags": ["并列", "要点"]}], "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                "history_note": "独立文字夹具，不用于制作或批准视频"},
                "overlay_alignment": [{"segment_id": "seg-smoke", "component_id": "scene", "brief_path": relative}],
                "overlay_selection": [{"segment_id": "seg-smoke", "component_id": "scene",
                    "intent_relation": "parallel", "native_route": "grid-card-assemble",
                    "visible_action": "staggered_card_reveal", "visual_structure": "grid-list",
                    "selection_reason": "此理由不作为证据"}], "semantic_assessments": [assessment]}
            treatment["semantic_lists"]["overlay"][0].update(start_word=1, end_word=2, quote=words[1]["text"])
            treatment = self.complete_overlay_cache(draft, treatment)
            report = motion.check_offline_plan(ROOT, draft, treatment, job_dir=root)
            self.assertEqual(report["status"], "pass", report)
            self.assertFalse(report["checks"][0]["retrieval"]["has_motion_basis"])
            self.assertEqual(report["checks"][0]["semantic"]["judged_by"], "host")
            self.assertEqual(report["checks"][0]["native_input"]["status"], "pass")
            # A host finding of reversed meaning must dominate valid native inputs.
            altered = copy.deepcopy(treatment)
            altered["semantic_assessments"][0].update(verdict="fail", reason="原声否定云API，但画面要求必须调用，含义相反。")
            self.assertEqual(motion.check_offline_plan(ROOT, draft, altered, job_dir=root)["status"], "fail")
            for case in ("missing", "duplicate", "changed_content", "changed_words", "future_context"):
                altered = copy.deepcopy(treatment)
                record = altered["semantic_assessments"][0]
                if case == "missing":
                    altered["semantic_assessments"] = []
                elif case == "duplicate":
                    altered["semantic_assessments"].append(copy.deepcopy(record))
                elif case == "changed_content":
                    record["content_refs"][0]["sha256"] = "c" * 64
                elif case == "changed_words":
                    record["transcript_refs"][0]["quote"] = "需要云API"
                else:
                    record["transcript_refs"][1] = {"start_word": 2, "end_word": 3,
                        "quote": words[2]["text"], "basis": "recap"}
                with self.subTest(case=case):
                    self.assertEqual(motion.check_offline_plan(ROOT, draft, altered, job_dir=root)["status"], "needs_review")
            # A tag hit alone still cannot produce semantic approval.
            altered = copy.deepcopy(treatment)
            altered["semantic_assessments"] = []
            report = motion.check_offline_plan(ROOT, draft, altered, job_dir=root)
            self.assertEqual(report["checks"][0]["query_tags"], ["并列", "要点"])
            self.assertEqual(report["status"], "needs_review")
            # The managed publication seam consumes the same check before freezing.
            path = root / "treatment.json"
            write("treatment.json", treatment)
            (root / "00-user-provided").mkdir()
            job = SimpleNamespace(root=root, job_dir=root)
            self.assertEqual(visual_plan._skill_selection_for_publication(job, draft, path)["motion_review"]["status"], "pass")
            write("treatment.json", altered)
            with self.assertRaisesRegex(visual_plan.VisualPlanError, "motion semantic/native input check"):
                visual_plan._skill_selection_for_publication(job, draft, path)

    def test_registered_native_validators_are_reused_without_rendering(self):
        from edit.hd.tools import motion_capabilities as motion

        catalog = motion.load_catalog(ROOT)
        modules = {row["adapter_module"]: row for row in catalog
                   if row["status"] == "supported" and row.get("adapter_module")}
        for name, row in modules.items():
            with self.subTest(adapter=name):
                self.assertEqual(motion._native_input_check(ROOT, row, {})["status"], "fail")
        source = {"aroll_sha256": "a" * 64, "segment_id": "seg-smoke", "start": 0, "end": 6}
        request = {"semantic_family": "old_new_comparison", "information_units": 2,
                   "numeric_values": [], "numeric_scale": "not_applicable"}
        adu = {"schema_version": 1, "source_binding": source, "template_request": request,
            "composition": {"id": "smoke", "width": 1080, "height": 1920, "fps": 24, "frames": 144},
            "typography": {"title_px": 64, "body_px": 36},
            "title": "做法比较", "left": {"title": "旧", "items": ["手动反复"]},
            "right": {"title": "新", "items": ["拆分步骤"]},
            "left_frame": 0, "right_frame": 24, "strike_frame": 72, "stamp": "拆开"}
        huashu = {"schema_version": 1, "dependency_id": "huashu-art-motion", "source_binding": source,
            "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 144},
            "template_request": {**request, "semantic_family": "process_flow", "information_units": 3},
            "props": {"data": {"grammar": "y1_kurzgesagt", "data": {"center": "取到写回", "flow": True},
                "safe": {"top": 100, "bottom": 300}, "cues": [
                    {"at": index, "kind": "point", "text": label}
                    for index, label in enumerate(("取材料", "交给模型", "写回文档"), 1)]}}, "assets": []}
        values, _ = selection._declarations(ROOT / "skill-development/hd-talking-head/scripts/openfilm_runtime.py")
        openfilm = {"schema_version": 1, "source_binding": source,
            "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 144, "alpha": False},
            "template_request": {**request, "semantic_family": "subject_action", "information_units": 1},
            "entry": {"media_ref": "entry", "job_path": "native/index.html", "scene_path": "index.html", "sha256": "b" * 64},
            "assets": [], "upstream": {"package_version": values["PACKAGE_VERSION"], "skill_sha256": "a" * 64, "manual_sha256": "a" * 64},
            "creative_handoff": {"transcript": "交给流程", "semantic_goal": "转交任务", "required_change": "交接",
                "subject": "任务纸", "visual_pattern": "subject_action", "style_reason": "清楚可见",
                "forbidden_outcomes": ["不虚构成功结果"], "beats": [{"start_frame": 0, "end_frame": 72,
                    "spoken_anchor": "交给", "before": "待交接", "action": "转交任务纸", "after": "已交接"}]}}
        for module, brief in (("adu_native_adapter", adu), ("huashu_motion_adapter", huashu),
                              ("openfilm_motion_adapter", openfilm)):
            with self.subTest(adapter=module):
                report = motion._native_input_check(ROOT, modules[module], brief)
                self.assertEqual(report["status"], "pass", report)
        design = next(row for row in catalog if row.get("role") == "design")
        self.assertEqual(motion._native_input_check(ROOT, design, None)["status"], "not_applicable")

    def test_approved_speech_reads_complete_transcript_and_maps_words(self):
        from edit.hd.tools import motion_capabilities as motion

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = {"version": 1, "words": [{"text": "测试", "start": 1.0, "end": 2.0}]}
            timeline = {"segments": [{"source_start": 1.0, "source_end": 2.0,
                                      "timeline_start": 0.0, "timeline_end": 1.0}]}
            workflow = {"stages": {}}
            for stage, relative, content in (
                ("speech_cleanup", "05-speech-cleanup/word-transcript.json", transcript),
                ("edit_structure", "06-edit-structure/timeline-map.json", timeline),
            ):
                path = root / relative
                path.parent.mkdir()
                path.write_text(json.dumps(content), encoding="utf-8")
                workflow["stages"][stage] = {"status": "approved", "artifacts": [{
                    "path": relative, "sha256": motion.contract_artifacts.sha256_file(path),
                    "bytes": path.stat().st_size}]}
            (root / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")

            self.assertEqual(motion._approved_speech(root), [
                {"text": "测试", "start": 0.0, "end": 1.0}])

    def test_motion_library_rejects_weak_matches_and_unqualified_inputs(self):
        from edit.hd.tools import motion_capabilities as motion

        catalog = motion.load_catalog(ROOT)
        fixed = [r for r in catalog if r["capability"]["content_scope"]["mode"] == "fixed_action"]
        self.assertEqual(motion.search_capabilities(ROOT,
            "完全不相关的海边日落宠物散步", use="broll", catalog=fixed), [])
        self.assertEqual(motion.search_capabilities(ROOT,
            "精致 浅暖色 人物", use="broll", catalog=fixed), [])
        matches = motion.search_capabilities(ROOT, "来源 汇聚 多到一", use="broll", catalog=catalog)
        converge = next(row for row in matches if row["candidate_id"].endswith("/source-converge.tsx"))
        self.assertIn("汇聚", converge["matched_dimensions"]["actions"])
        # Archived card qualification still validates its own public fields;
        # it does not make this card a callable production capability.
        cases = motion.contract_artifacts.read_json_artifact(ROOT /
            "edit/hd/integrations/talkcraft/runtime/qualification-cases/stage-keyframe-tour.json")["cases"]
        stage = {"template_id": "hd-talking-head/talkcraft/stage-keyframe-tour",
                 "native_contract": {"qualified_raw_field_sets": [list(keys) for keys in
                 sorted({tuple(sorted(case["raw"])) for case in cases})]}}
        self.assertEqual(stage["native_contract"]["qualified_raw_field_sets"], [["accent", "subtitle", "title"]])
        brief = {"card_id": "stage-keyframe-tour", "events": [{"payload": {"raw": {
            "title": "实际资料", "subtitle": "长报表", "accent": "#123456", "screenshot": "report.png"}}}]}
        with self.assertRaisesRegex(ValueError, "outside the qualified native fields"):
            motion._check_talkcraft_fields(stage, brief)
        del brief["events"][0]["payload"]["raw"]["screenshot"]
        self.assertTrue(motion._check_talkcraft_fields(stage, brief))
        for raw in ({}, {"title": "实际资料"}, {"title": "实际资料", "accent": "#123456"}):
            missing = {"card_id": "stage-keyframe-tour", "events": [{"payload": {"raw": raw}}]}
            self.assertFalse(motion._check_talkcraft_fields(stage, missing))
        multiple = copy.deepcopy(brief)
        multiple["events"].append({"payload": {"raw": {"title": "不完整"}}})
        self.assertFalse(motion._check_talkcraft_fields(stage, multiple))
        alternate = copy.deepcopy(stage)
        alternate["native_contract"]["qualified_raw_field_sets"] = [["title", "accent"], ["title", "subtitle"]]
        self.assertFalse(motion._check_talkcraft_fields(alternate, brief))
        alternate_brief = {"card_id": "stage-keyframe-tour", "events": [
            {"payload": {"raw": {"title": "实际资料", "accent": "#123456"}}}]}
        self.assertTrue(motion._check_talkcraft_fields(alternate, alternate_brief))
        self.assertEqual(motion._brief_overlay_route({"upstream_route": "hyperframes/toggle-flip"}), "toggle-flip")

        read = motion.contract_artifacts.read_json_artifact
        altered = copy.deepcopy(read(ROOT / motion.INDEX))
        profile = altered["profiles"][0]
        first = next(iter(profile["reviewed_sources"]))
        profile["reviewed_sources"][first] = "0" * 64
        with patch.object(motion.contract_artifacts, "read_json_artifact",
                          side_effect=lambda path: altered if Path(path) == ROOT / motion.INDEX else read(path)):
            with self.assertRaisesRegex(ValueError, "source changed; review"):
                motion.load_profiles(ROOT)

    def test_offline_motion_check_never_uses_selection_reason_as_evidence(self):
        from edit.hd.tools import motion_capabilities as motion

        catalog = motion.load_catalog(ROOT)
        pin = next(row for row in catalog if row["candidate_id"] == "overlay:pin-board")
        binding = {k: pin[k] for k in ("dependency_id", "entrypoint", "producer_version", "template_id")}
        segment = {"segment_id": "overlay-case", "start": 0, "end": 5,
            "visual_strategy": {"mode": "none", "composition": {"family": "aroll_with_overlay"},
                                 "components": [{"component_id": "scene", "kind": "code_generated", "brief": "并列说明"}]},
            "bindings": {"scene": binding}}
        draft = {"segments": [segment]}
        treatment = {"semantic_lists": {"overlay": [{"row_id": "row-overlay", "start_word": 0, "end_word": 1, "quote": "并列要点", "semantic": "并列", "visual_task": "标注", "components": [{"segment_id": "overlay-case", "component_id": "scene"}]}], "broll": []}, "motion_queries": [{"segment_id": "overlay-case", "component_id": "scene", "tags": ["并列", "要点"]}], "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
            "history_note": "仅离线结构样本，无媒体执行"}, "overlay_selection": [{
            "segment_id": "overlay-case", "component_id": "scene", "intent_relation": "parallel",
            "native_route": "pin-board", "visible_action": "cumulative_pin_drop",
            "visual_structure": "pin-board", "selection_reason": "海边日落"}]}
        treatment = self.complete_overlay_cache(draft, treatment)
        report = motion.check_offline_plan(ROOT, draft, treatment)
        treatment["overlay_selection"][0]["selection_reason"] = "并列 要点 累积 pin-board"
        self.assertEqual(report, motion.check_offline_plan(ROOT, draft, treatment))
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report["checks"][0]["retrieval"]["has_motion_basis"])
        self.assertTrue(any(row["check"] == "approved_spoken_text" for row in report["not_verified"]))
        with patch.object(motion, "_approved_speech", return_value=[{"text": "并列要点", "start": 0, "end": 3}]), \
             patch.object(motion, "_bound_brief", return_value={"upstream_route": "hyperframes/toggle-flip"}):
            with self.assertRaisesRegex(ValueError, "actual native brief route differs"):
                motion.check_offline_plan(ROOT, draft, treatment)

    def test_unified_motion_library_preserves_roles_and_native_qualification(self):
        from edit.hd.tools import motion_capabilities as motion

        catalog = motion.load_catalog(ROOT)
        by_id = {row["candidate_id"]: row for row in catalog}
        self.assertFalse(any(cid.startswith("hd-talking-head-talkcraft:") for cid in by_id))
        self.assertEqual(len([cid for cid in by_id if cid.startswith("talkcraft-native-adaptation:")]), 4)
        self.assertEqual(len([cid for cid in by_id if cid.startswith("overlay:")]), 9)
        added = [row for row in catalog if row['skill_id'] in {'barty-motion-graphics', 'bang-motion'}]
        self.assertEqual(len({selection._template_identity(row) for row in added}), 39)
        self.assertEqual({row['skill_id'] for row in added}, {'barty-motion-graphics', 'bang-motion'})
        self.assertEqual(selection._template_identity(by_id['overlay:barty-motion-graphics/motion-broll']),
                         selection._template_identity(by_id['barty-motion-graphics:barty-motion-graphics/motion-broll']))
        self.assertFalse(any(cid.startswith(("history:", "unconnected:"))
                             for cid in by_id))
        self.assertEqual({row['status'] for row in catalog}, {'supported'})
        self.assertIn('paper-collage-hyperframes:paper-collage-ad/hyperframes', by_id)
        native = [row for row in catalog if row['skill_id'] == 'video-talkcraft']
        self.assertEqual(len(native), 108)
        self.assertEqual(sum(row['native_role'] == 'scene' for row in native), 51)
        self.assertEqual(selection.source_channel('paper-collage-ad'),
                         selection.source_channel('paper-collage-hyperframes'))
        self.assertEqual(selection.source_channel('video-talkcraft'),
                         selection.source_channel('talkcraft-native-adaptation'))
        self.assertEqual(motion.catalog_summary(catalog)['total'], len(by_id))
        unavailable = copy.deepcopy(by_id["overlay:pin-board"])
        unavailable['status'] = 'needs_adapter'
        self.assertEqual(motion.search_capabilities(ROOT, "并列 要点 累积", catalog=[unavailable]), [])
        overlays = motion.search_capabilities(ROOT, "并列 要点 累积", use="aroll_overlay", catalog=catalog)
        self.assertIn("overlay:pin-board", {row["candidate_id"] for row in overlays})
        self.assertFalse(any(row["candidate_id"].startswith("hd-talking-head-talkcraft:") for row in overlays))
        self.assertFalse(any(row["status"] == "excluded" for row in overlays))
        pin = by_id["overlay:pin-board"]
        wrong_role = next(row for row in catalog if row.get("skill_id") == "openfilm-motion-graphics")
        with self.assertRaisesRegex(ValueError, "differs from the registered use"):
            motion.validate_overlay_capability("pin-board", wrong_role)
        profiles = motion.load_profiles(ROOT)
        profiles[pin["candidate_id"]]["reviewed_version"] = "unreviewed-update"
        with self.assertRaisesRegex(ValueError, "version changed"):
            motion.describe_candidates(ROOT, [pin], use="aroll_overlay", profiles=profiles)

    def test_three_real_lines_assignment_and_publication_binding(self):
        pool = selection.discover_candidates(ROOT)
        skills = {c["skill_id"] for c in pool}
        by_template = {c["template_id"]: c for c in pool}
        flat = by_template["muyang-flat-animation/design"]
        vox = by_template["huashu-art-motion/y2_vox"]
        doudou = by_template["doudou-reviewed-scene"]
        carousel = by_template["hyperframes-screen-flow-carousel-portrait-adaptation"]
        self.assertIn("wise-motion/orbit-tracking-component", by_template)
        openfilm = by_template["openfilm/motion-graphics-scene"]
        self.assertEqual(openfilm["source_route"], "motion-graphics")
        self.assertEqual(openfilm["role"], "native")
        self.assertEqual(openfilm["semantic_families"], [])
        self.assertFalse(any("canonical" in c["candidate_id"] or c["skill_id"] == "onetake" for c in pool))
        self.assertEqual(len({c["template_id"] for c in pool if c["skill_id"] == "lemo-opuscar"}), 59)
        # Real wording from 3.docx/Scribe, not new claims or revised narration.
        cases = [
            ("我接了个兼职，活干完了，但是钱却迟迟拿不到。", "交付后仍未收到报酬", [flat], ["deliver-unpaid"]),
            ("但是这一定是要自己去核对原始的聊天记录。", "人核对原始材料", [vox], ["source-check-highlight"]),
            ("找出当初谈好的报酬对话，再找出活已经做了交付的凭证。", "区分约定与交付凭证", [doudou, carousel], ["handdrawn-evidence-groups", "screen-flow"]),
        ]
        beats = []
        for index, (line, change, candidates, patterns) in enumerate(cases):
            reviews = {sid: {"fit": "unsuitable", "reason": "该入口不满足本句所需主体动作、信息结构或真实材料条件"} for sid in skills}
            for candidate in candidates:
                reviews[candidate["skill_id"]] = {"fit": "equivalent", "reason": change}
            beats.append({"segment_id": f"seg-{index + 1}", "component_id": "scene",
                          "start": index * 8, "end": index * 8 + 6,
                          "transcript": line, "semantic_goal": change, "required_change": change,
                          "skill_reviews": reviews,
                          "candidates": [{"candidate_id": c["candidate_id"],
                                          "fit": "preferred" if len(candidates) == 1 else "equivalent",
                                          "reason": change, "visual_pattern": pattern}
                                         for c, pattern in zip(candidates, patterns)]})
        source = {"schema_version": 1, "beats": beats,
                  "history_note": "用已观察到的上一条屏幕轮播测试重复协调；非新的媒体验收",
                  "recent_context": [{"source_ref": "previous-preview:screen-flow-carousel", "video_id": "previous",
                                      "skill_id": carousel["skill_id"], "visual_pattern": "screen-flow", "start": 0, "end": 20}]}
        assigned = selection.assign_skills(ROOT, source)
        # Both choices add a channel and a template. With those maxima tied,
        # avoid the carousel already used throughout the previous video.
        self.assertEqual([a["skill_id"] for a in assigned["assignments"]],
                         [flat["skill_id"], vox["skill_id"], doudou["skill_id"]])
        self.assertEqual(selection.assign_skills(ROOT, assigned), assigned)
        # Snapshots are planned inputs, not fabricated execution success receipts.
        draft = {"segments": []}
        for beat, assignment in zip(assigned["beats"], assigned["assignments"]):
            candidate = next(c for c in pool if c["candidate_id"] == assignment["candidate_id"])
            binding = ({"provider": "lovart", "model": "kling-o1", "prompt_sha256": "a" * 64}
                       if candidate["role"] == "design" else
                       {k: candidate[k] for k in ("dependency_id", "entrypoint", "template_id", "producer_version")})
            if candidate["role"] == "design":
                binding.update(execution_mode="reuse_completed_generated_media", generation_id="generation-1", sha256="c" * 64)
            binding["brief_sha256"] = "b" * 64
            binding["source_dimensions"] = {"width": 1080, "height": 1920, "fps": 24}
            beat.update(intent_statement=beat["semantic_goal"], component_brief=beat["required_change"],
                        binding_snapshot=copy.deepcopy(binding))
            draft["segments"].append({"segment_id": beat["segment_id"], "start": beat["start"], "end": beat["end"],
                                      "visual_intent": {"statement": beat["intent_statement"]},
                                      "visual_strategy": {"mode": "single", "composition": {"family": "single_full_frame"}, "components": [{"component_id": "scene",
                                          "kind": "ai_generated" if candidate["role"] == "design" else "code_generated",
                                          "brief": beat["component_brief"]}]}, "bindings": {"scene": binding}})
        treatment = {"skill_selection": assigned}
        report = selection.validate_selection(ROOT, draft, treatment)
        self.assertEqual(report["status"], "pass")
        frozen = copy.deepcopy(draft["segments"])
        for segment in frozen:
            segment["shot_recipe"] = {"components": [{"component_id": "scene", **segment["bindings"]["scene"],
                "artifact_contract": {"width": 1080, "height": 1920, "fps": 24}}]}
        visual_plan._check_selected_recipe_bindings(draft, frozen, report)
        frozen[0]["shot_recipe"]["components"][0]["brief_sha256"] = "c" * 64
        with self.assertRaisesRegex(visual_plan.VisualPlanError, "compiled recipe changed"):
            visual_plan._check_selected_recipe_bindings(draft, frozen, report)
        for mutate in ("binding", "brief", "window", "missing", "assignment"):
            altered, altered_treatment = copy.deepcopy(draft), copy.deepcopy(treatment)
            if mutate == "binding":
                altered["segments"][0]["bindings"]["scene"]["brief_sha256"] = "c" * 64
            elif mutate == "brief":
                altered["segments"][0]["visual_strategy"]["components"][0]["brief"] = "另一种动作"
            elif mutate == "window":
                altered["segments"][0]["end"] += 1
            elif mutate == "missing":
                altered_treatment["skill_selection"]["beats"].pop()
            else:
                altered_treatment["skill_selection"]["assignments"][0]["candidate_id"] = carousel["candidate_id"]
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                selection.validate_selection(ROOT, altered, altered_treatment)

    def test_managed_gate_cannot_be_bypassed_and_bare_runtime_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = SimpleNamespace(root=root)
            self.assertIsNone(visual_plan._skill_selection_for_publication(job, {}, None))
            (root / "00-user-provided").mkdir()
            with self.assertRaisesRegex(visual_plan.VisualPlanError, "selection is required"):
                visual_plan._skill_selection_for_publication(job, {}, None)

    def test_candidate_pool_uses_only_verified_and_complete_sources(self):
        pool = selection.discover_candidates(ROOT)
        template_ids = {row["template_id"] for row in pool}
        self.assertNotIn("hyperframes/chatgpt-exchange", template_ids)
        self.assertNotIn("hyperframes-before-after-wipe-portrait-adaptation", template_ids)
        self.assertNotIn("hyperframes-toggle-flip-portrait-adaptation", template_ids)
        self.assertNotIn("hyperframes-grid-card-assemble-portrait-adaptation", template_ids)
        self.assertNotIn("hyperframes-notification-stack-portrait-adaptation", template_ids)
        self.assertEqual(
            {row["template_id"] for row in pool if row["skill_id"] == "hyperframes-native-adaptation"},
            {
                "hyperframes-macos-notification-portrait-adaptation",
                "hyperframes-chat-message-portrait-adaptation",
                "hyperframes-screen-flow-carousel-portrait-adaptation",
                "hyperframes-beat-timeline-portrait-adaptation",
            },
        )
        self.assertIn("muyang-flat-animation/design", template_ids)
        self.assertIn("gbro-collage-broll/design", template_ids)
        self.assertIn("hyperframes/notification-cascade", template_ids)
        self.assertIn("html-video/frame-data-rollup", template_ids)

        read_artifact = selection.contract_artifacts.read_json_artifact

        def without_qualified_templates(path):
            artifact = read_artifact(path)
            if Path(path).name == "verified-template-registry.json":
                artifact = copy.deepcopy(artifact)
                artifact["templates"] = [record for record in artifact["templates"]
                                         if record["template_origin"] != "verified_third_party"]
            return artifact

        with patch.object(selection.contract_artifacts, "read_json_artifact",
                          side_effect=without_qualified_templates):
            remaining = selection.discover_candidates(ROOT)
        self.assertFalse(any(row["template_id"] in template_ids and
                             (row["template_id"].startswith("huashu-art-motion/") or
                              row["template_id"] in {"html-video/frame-data-rollup",
                                                      "hyperframes/notification-cascade"})
                             for row in remaining))
        self.assertIn("hyperframes-chat-message-portrait-adaptation",
                      {row["template_id"] for row in remaining})

    def test_invalid_candidate_is_rejected_before_binding(self):
        pool = selection.discover_candidates(ROOT)
        skills = {row["skill_id"] for row in pool}
        reviews = {skill: {"fit": "unsuitable", "reason": "不适用"} for skill in skills}
        source = {"schema_version": 1, "beats": [{
            "segment_id": "seg-invalid", "component_id": "scene", "start": 0, "end": 1,
            "transcript": "测试", "semantic_goal": "测试", "required_change": "测试",
            "skill_reviews": reviews,
            "candidates": [{"candidate_id": "hyperframes:hyperframes/chatgpt-exchange",
                            "fit": "preferred", "reason": "测试", "visual_pattern": "screen"}],
        }], "history_note": "测试"}
        with self.assertRaisesRegex(ValueError, "not discovered"):
            selection.assign_skills(ROOT, source)

    def test_native_overlays_are_adjustable_and_not_fixed_context(self):
        def candidate(cid, skill, template, role="native"):
            return {"candidate_id": cid, "skill_id": skill, "dependency_id": skill,
                    "template_id": template, "role": role, "status": "supported",
                    "entrypoint": "native-entry", "producer_version": "1", "limitations": []}
        native = [candidate("a", "hyperframes", "native-a"), candidate("b", "paper", "native-b")]
        overlay = candidate("overlay:test", "hyperframes", "native-overlay", "aroll_overlay")
        def beat(sid, cid, choices, start):
            binding = {key: choices[0][key] for key in ("dependency_id", "entrypoint", "template_id", "producer_version")}
            return {"segment_id": sid, "component_id": cid, "start": start, "end": start + 2,
                    "transcript": "解释", "semantic_goal": "解释", "required_change": "展示",
                    "intent_statement": "解释", "component_brief": "展示", "binding_snapshot": binding,
                    "skill_reviews": {row["skill_id"]: {"fit": "equivalent", "reason": "已审阅"} for row in native},
                    "candidates": [{"candidate_id": row["candidate_id"], "fit": "equivalent",
                                    "reason": "已审阅", "visual_pattern": "native"} for row in choices]}
        base = beat("b", "scene", [native[1], native[0]], 0)
        annotation = beat("o", "annotation", [overlay], 2)
        source = {"schema_version": 1, "beats": [base], "overlay_beats": [annotation],
                  "fixed_context": [], "history_note": "独立联合分配测试"}
        draft = {"segments": []}
        for row, family in ((base, "single_full_frame"), (annotation, "aroll_with_overlay")):
            draft["segments"].append({"segment_id": row["segment_id"], "start": row["start"], "end": row["end"],
                "visual_intent": {"statement": "解释"}, "visual_strategy": {"mode": "single" if family == "single_full_frame" else "none",
                    "composition": {"family": family}, "components": [{"component_id": row["component_id"],
                        "kind": "code_generated", "brief": "展示"}]},
                "bindings": {row["component_id"]: copy.deepcopy(row["binding_snapshot"])}})
        with patch.object(selection, "discover_candidates", return_value=native), \
             patch("edit.hd.tools.motion_capabilities.overlay_candidates", return_value=[overlay]):
            assigned = selection.assign_skills(ROOT, source)
            self.assertEqual(assigned["assignments"][0]["candidate_id"], "b")
            self.assertEqual(assigned["overlay_assignments"][0]["candidate_id"], "overlay:test")
            treatment = {"skill_selection": assigned}
            selection.validate_selection(ROOT, draft, treatment)
            for mutation in ("missing", "fixed"):
                altered = copy.deepcopy(treatment)
                if mutation == "missing":
                    altered["skill_selection"]["overlay_beats"] = []
                else:
                    altered["skill_selection"]["fixed_context"] = [{"segment_id": "o", "component_id": "annotation",
                        "start": 2, "end": 4, "skill_id": "hyperframes", "template_id": "native-overlay",
                        "source_ref": "not-an-independent-fixed-material", "visual_pattern": "native"}]
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    selection.validate_selection(ROOT, draft, altered)

    def test_design_templates_participate_in_template_identity(self):
        def candidate(skill, role):
            return {"candidate_id":skill, "skill_id":skill, "role":role,
                    "template_id":skill+'/workflow', "entrypoint":'entry',
                    "limitations":[], "status":"supported"}
        pool = [candidate('gbro','design'),candidate('native','native')]
        def beat(index):
            return {"segment_id":f'seg-{index}',"component_id":"scene","start":index*3,"end":index*3+3,
                "transcript":"quote","semantic_goal":"meaning","required_change":"change",
                "skill_reviews":{r['skill_id']:{"fit":"equivalent","reason":"eligible"} for r in pool},
                "candidates":[{"candidate_id":r['candidate_id'],"fit":"preferred" if r['skill_id']=='gbro' else 'equivalent',
                    "reason":"eligible","visual_pattern":"objects"} for r in pool]}
        draft = {"schema_version":1,"history_note":"none","beats":[beat(0)]}
        from edit.hd.tools import motion_capabilities
        with patch.object(selection,'discover_candidates',side_effect=lambda _:pool), \
             patch.object(motion_capabilities,'overlay_candidates',return_value=[]):
            result = selection.assign_skills(ROOT,draft)
            self.assertEqual(result['assignments'][0]['skill_id'],'gbro')
            pool[1] = candidate('flat','design')  # Both can use the same underlying provider.
            draft['beats'] = [beat(0),beat(1)]
            result = selection.assign_skills(ROOT,draft)
            self.assertEqual({a['skill_id'] for a in result['assignments']},{'gbro','flat'})
            draft['fixed_context'] = [{"segment_id":"seg-fixed","component_id":"fixed","start":8,"end":9,
                "source_ref":"unverified.mp4","skill_id":"gbro","template_id":None,"visual_pattern":"objects"}]
            draft['beats'] = [beat(0)]
            result = selection.assign_skills(ROOT,draft)
            self.assertEqual(result['assignments'][0]['skill_id'],'gbro')

    def test_fixed_generated_media_does_not_use_provider_as_skill_channel(self):
        draft = {"segments": [{"segment_id": "seg-fixed", "start": 0, "end": 2,
            "visual_strategy": {"components": [{"component_id": "scene",
                "kind": "ai_generated"}]},
            "bindings": {"scene": {"provider": "lovart", "generation_id": "g1",
                "execution_mode": "reuse_completed_lovart_video"}}}]}
        selection.validate_fixed_materials(draft, {"beats": [], "overlay_beats": [],
            "fixed_context": [{"segment_id": "seg-fixed", "component_id": "scene",
                "start": 0, "end": 2, "skill_id": "gbro-collage-broll",
                "template_id": None, "source_ref": "job/media.mp4",
                "visual_pattern": "collage"}], "history_note": "test"})

    def test_semantic_image_evidence_requires_current_bound_picture(self):
        from PIL import Image
        from edit.hd.tools import motion_capabilities as motion

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            picture = root / "picture.png"
            Image.new("RGB", (8, 8), "#f4ebdd").save(picture)
            brief = {"assets": [{"job_path": "picture.png", "sha256": motion.contract_artifacts.sha256_file(picture)}]}
            path = root / "brief.json"
            path.write_text(json.dumps(brief))
            segment = {"segment_id": "picture", "start": 0, "end": 1,
                       "bindings": {"scene": {"brief_sha256": motion.contract_artifacts.sha256_file(path)}}}
            assessment = {"segment_id": "picture", "component_id": "scene", "candidate_id": "picture-scene",
                "verdict": "pass", "reason": "A synthetic picture tests identity and decoding, not production semantics.",
                "transcript_refs": [{"start_word": 0, "end_word": 1, "quote": "示意", "basis": "current_clause"}],
                "content_refs": [{"path": "picture.png", "sha256": brief["assets"][0]["sha256"], "image": True}]}
            treatment = {"scenes": [{"segment_id": "picture", "component_id": "scene", "brief_path": "brief.json"}],
                         "semantic_assessments": [assessment]}
            row = {"candidate_id": "picture-scene", "capability": {"capability_type": "native_component"}}
            speech = [{"text": "示意", "start": 0, "end": 1}]
            def check(candidate=row):
                return motion._semantic_assessment(root, treatment, segment, "scene", candidate, speech, brief)
            self.assertEqual(check()["status"], "pass")
            creative = {**row, "capability": {"capability_type": "creative_skill"}}
            self.assertEqual(check(creative)["status"], "needs_review")
            assessment["content_refs"][0]["image"] = False
            self.assertEqual(check()["status"], "needs_review")
            assessment["content_refs"][0]["image"] = True
            assessment["content_refs"][0]["path"] = "unbound.png"
            self.assertEqual(check()["status"], "needs_review")
            assessment["content_refs"][0]["path"] = "picture.png"
            picture.write_bytes(b"not an image")
            # Matching checksums alone must not qualify non-image bytes.
            digest = motion.contract_artifacts.sha256_file(picture)
            brief["assets"][0]["sha256"] = digest
            assessment["content_refs"][0]["sha256"] = digest
            path.write_text(json.dumps(brief))
            segment["bindings"]["scene"]["brief_sha256"] = motion.contract_artifacts.sha256_file(path)
            self.assertEqual(check()["status"], "needs_review")

    def test_native_creation_templates_share_the_diversity_objective(self):
        """A registered style counts like a component, not like each new scene."""
        for skill in ("openfilm-motion-graphics", "doudou-remotion-whiteboard",
                      "whiteboard-video", "paper-collage-ad"):
            with self.subTest(skill=skill):
                pool = [{"candidate_id": cid, "skill_id": skill, "template_id": template,
                         "role": "native", "status": "supported", "entrypoint": "native-entry",
                         "producer_version": "1", "limitations": []}
                        for cid, template in (("a", "style-a"), ("b", "style-b"),
                                              ("z", "style-a"))]
                def beat(index, choices):
                    return {"segment_id": f"s{index}", "component_id": "scene",
                            "start": index * 3, "end": index * 3 + 2,
                            "transcript": "整理信息", "semantic_goal": "整理信息",
                            "required_change": "归类", "skill_reviews": {
                                skill: {"fit": "equivalent", "reason": "已核对原生能力"}},
                            "candidates": [{"candidate_id": cid, "fit": fit,
                                            "reason": "语义与画面均适合", "visual_pattern": "same"}
                                           for cid, fit in choices]}
                source = {"schema_version": 1, "history_note": "仅测试已登记模板的分配",
                          "beats": [beat(0, [("a", "preferred")]),
                                    beat(1, [("a", "preferred"), ("b", "equivalent")])]}
                with patch.object(selection, "discover_candidates", return_value=pool):
                    result = selection.assign_skills(ROOT, source)
                    self.assertEqual([row["candidate_id"] for row in result["assignments"]],
                                     ["a", "b"])
                    self.assertEqual({selection.source_channel(row["skill_id"])
                                      for row in result["assignments"]}, {skill})
                    # Another current project or alias of the same style is
                    # still one template, even when it is locally preferred.
                    source["beats"][1] = beat(1, [("b", "equivalent"), ("z", "preferred")])
                    self.assertEqual(selection.assign_skills(ROOT, source)["assignments"][1]
                                     ["candidate_id"], "b")

    def test_talkcraft_aliases_do_not_reward_repeating_the_same_native_card(self):
        cards = ('info-term-card', 'number-counter', 'numbered-step-stack', 'source-converge')
        for card in cards:
            old = {'skill_id': 'talkcraft-native-adaptation', 'template_id': 'talkcraft-native-reviewed-scene',
                   'source_route': 'template/cards/' + card + '.tsx'}
            native = {'skill_id': 'video-talkcraft', 'template_id': 'video-talkcraft/' + card,
                      'source_route': card}
            before = copy.deepcopy(old)
            self.assertEqual(selection._template_identity(old), selection._template_identity(native))
            self.assertEqual(selection._template_identity({k: v for k, v in native.items() if k != 'source_route'}),
                             selection._template_identity(native))
            self.assertEqual(old, before)

        def candidate(cid, skill, template, route):
            return {'candidate_id': cid, 'skill_id': skill, 'template_id': template, 'source_route': route,
                    'role': 'native', 'status': 'supported', 'entrypoint': 'native-entry',
                    'producer_version': '1', 'limitations': []}
        pool = [candidate('legacy-info', 'talkcraft-native-adaptation', 'talkcraft-native-reviewed-scene',
                          'template/cards/info-term-card.tsx'),
                candidate('native-info', 'video-talkcraft', 'video-talkcraft/info-term-card', 'info-term-card'),
                candidate('native-number', 'video-talkcraft', 'video-talkcraft/number-counter', 'number-counter')]
        def beat(index, ids):
            return {'segment_id': 's' + str(index), 'component_id': 'scene', 'start': index * 3,
                    'end': index * 3 + 2, 'transcript': '说明当前项目', 'semantic_goal': '说明当前项目',
                    'required_change': '展示', 'skill_reviews': {row['skill_id']: {
                        'fit': 'equivalent', 'reason': '本夹具已审阅的原生入口'} for row in pool},
                    'candidates': [{'candidate_id': cid, 'fit': 'equivalent', 'reason': '语义可用',
                                    'visual_pattern': 'same'} for cid in ids]}
        source = {'schema_version': 1, 'history_note': '仅检查真实模板身份的离线夹具',
                  'beats': [beat(0, ['legacy-info']), beat(1, ['native-info', 'native-number'])]}
        from edit.hd.tools import motion_capabilities
        with patch.object(selection, 'discover_candidates', return_value=pool), \
             patch.object(motion_capabilities, 'overlay_candidates', return_value=[]):
            assigned = selection.assign_skills(ROOT, source)['assignments']
        self.assertEqual([row['candidate_id'] for row in assigned], ['legacy-info', 'native-number'])
        self.assertEqual(assigned[0]['source_route'], 'template/cards/info-term-card.tsx')
        self.assertEqual(assigned[0]['template_id'], 'talkcraft-native-reviewed-scene')

    def test_assignment_channel_and_template_diversity_offline(self):
        def candidate(cid, skill, template):
            return {"candidate_id": cid, "skill_id": skill, "template_id": template,
                    "role": "native", "status": "supported", "entrypoint": "native-entry",
                    "producer_version": "1", "limitations": []}

        pool = [candidate("a", "hyperframes-native-adaptation", "first"),
                candidate("b", "hyperframes", "second"),
                candidate("c", "riso", "title")]
        skills = {row["skill_id"] for row in pool}
        def beat(index, choices):
            return {"segment_id": f"s{index}", "component_id": "scene",
                    "start": index * 3, "end": index * 3 + 2,
                    "transcript": "整理信息", "semantic_goal": "整理信息", "required_change": "归类",
                    "skill_reviews": {sid: {"fit": "equivalent", "reason": "此夹具已审阅的候选"}
                                      for sid in skills},
                    "candidates": [{"candidate_id": cid, "fit": "equivalent", "reason": "可用",
                                    "visual_pattern": pattern} for cid, pattern in choices]}
        source = {"schema_version": 1, "beats": [beat(0, [("a", "same")]),
                  beat(1, [("b", "different"), ("c", "same")])], "history_note": "离线分配行为夹具",
                  "recent_context": [{"source_ref": "last-video", "video_id": "previous",
                                      "skill_id": "riso", "visual_pattern": "same", "start": 0, "end": 30}]}
        with patch.object(selection, "discover_candidates", return_value=pool):
            result = selection.assign_skills(ROOT, source)
            # The two HyperFrames adapters are one channel. History does not
            # claim a channel for this video; coverage precedes pattern preference.
            self.assertEqual([a["candidate_id"] for a in result["assignments"]], ["a", "c"])
            preferred = copy.deepcopy(source)
            preferred["beats"][1]["candidates"][0]["fit"] = "preferred"
            self.assertEqual(selection.assign_skills(ROOT, preferred)["assignments"][1]["candidate_id"], "c")
            unsupported = copy.deepcopy(pool)
            unsupported[2]["status"] = "needs_adapter"
            with patch.object(selection, "discover_candidates", return_value=unsupported):
                with self.assertRaisesRegex(ValueError, "not callable"):
                    selection.assign_skills(ROOT, source)
            # With one real channel available, use another actual template.
            same_channel = copy.deepcopy(source)
            same_channel["recent_context"] = []
            same_channel["beats"][1] = beat(1, [("a", "same"), ("b", "same")])
            self.assertEqual(selection.assign_skills(ROOT, same_channel)["assignments"][1]["candidate_id"], "b")
            # A shared execution wrapper can expose different real templates.
            routed = copy.deepcopy(pool)
            for row in routed[:2]:
                row.update(template_id="shared-wrapper", source_route="native/" + row["candidate_id"])
            with patch.object(selection, "discover_candidates", return_value=routed):
                self.assertEqual(selection.assign_skills(ROOT, same_channel)["assignments"][1]["candidate_id"], "b")

        # Alias IDs point at the same source/template. Neither single change
        # improves A/B/B; changing two positions reaches C/A/B.
        pool = [candidate("a", "A", "ta"), candidate("b", "B", "tb"),
                candidate("c", "C", "tc"), candidate("z", "A", "ta")]
        skills = {row["skill_id"] for row in pool}
        joint = {"schema_version": 1, "history_note": "联合替换夹具", "beats": [
            beat(0, [("a", "same"), ("c", "same")]),
            beat(1, [("b", "same"), ("z", "same")]), beat(2, [("b", "same")])]}
        with patch.object(selection, "discover_candidates", return_value=pool):
            result = selection.assign_skills(ROOT, joint)
            self.assertEqual([a["skill_id"] for a in result["assignments"]], ["C", "A", "B"])
            self.assertEqual(selection.assign_skills(ROOT, result), result)

    def test_local_revision_keeps_confirmed_routes_and_explicit_changes(self):
        from edit.hd.tools import visual_confirmation as confirmation, contract_artifacts
        from edit.hd.tools import motion_capabilities
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory).resolve()
            (job / "manifests").mkdir()
            def write(name, value):
                path = job / name
                path.parent.mkdir(parents=True, exist_ok=True)
                contract_artifacts.write_json_artifact(path, value)
                return confirmation._record(job, path)
            write("workflow.json", {"job_id": "revision-job"})
            config = write("manifests/provider-config.json", {"providers": []})
            pool = [{"candidate_id": key, "skill_id": key, "template_id": key + "/template",
                     "role": "native", "status": "supported", "entrypoint": "native-entry",
                     "producer_version": "1", "limitations": []} for key in ("a", "b")]
            def beat(index):
                return {"segment_id": "s" + str(index), "component_id": "scene",
                        "semantic_row_id": "r" + str(index), "start": index * 3, "end": index * 3 + 2,
                        "transcript": "原话", "semantic_goal": "当前任务", "required_change": "具体动作",
                        "intent_statement": "当前任务", "component_brief": "具体动作",
                        "skill_reviews": {k: {"fit": "equivalent", "reason": "已审"} for k in ("a", "b")},
                        "candidates": [{"candidate_id": k, "fit": "equivalent", "reason": "已审",
                                        "visual_pattern": k} for k in ("a", "b")]}
            old = {"schema_version": 1, "beats": [beat(0), beat(1)], "overlay_beats": [],
                   "assignments": [{"segment_id": "s0", "component_id": "scene", "candidate_id": "a"},
                                   {"segment_id": "s1", "component_id": "scene", "candidate_id": "b"}],
                   "overlay_assignments": [], "history_note": "真实确认后的局部修订"}
            fixed = {"segment_id": "s2", "component_id": "scene", "start": 6, "end": 8,
                     "source_ref": "本地素材", "visual_pattern": "静态", "skill_id": "local_material"}
            old["fixed_context"] = [fixed]
            director = {"segments": [{"segment_id": "s" + str(i), "start": i * 3, "end": i * 3 + 2,
                         "bindings": {"scene": {"source": "same"}}, "visible_text": ["原文字"],
                         "visual_strategy": {"components": [
                             {"component_id": "scene", "kind": "local_material" if i == 2 else "code_generated"}],
                             "composition": {"family": "single_full_frame", "presenter_mode": "bottom_window",
                                             "avatar": {"position": "right"}}}}
                        for i in range(3)]}
            lists = {"broll": [{"row_id": "r" + str(i), "components": [
                {"segment_id": "s" + str(i), "component_id": "scene"}], "semantic": "原语义"}
                for i in range(3)], "overlay": []}
            old_treatment = {"skill_selection": old, "semantic_lists": lists, "numbering_scope_id": "scope"}
            treatment_ref = write("old/treatment.json", old_treatment)
            director_ref = write("old/director.json", director)
            proposal = write("old/proposal.json", {"kind": confirmation.SCHEMA, "job_id": "revision-job",
                "inputs": {"treatment": treatment_ref, "director": director_ref},
                "numbering_scope_id": "scope", "numbering": {"r0": 1, "r1": 2, "r2": 3},
                "provider_config_sha256": config["sha256"],
                "rows": [{"semantic_row_id": "r" + str(i), "segment_id": "s" + str(i),
                          "component_id": "scene"} for i in range(3)]})
            receipt = write("manifests/local-qa-visual_direction-r1.json", {"source_schema": confirmation.SCHEMA,
                "job_id": "revision-job", "job_dir": str(job), "stage": "visual_direction",
                "passed": True, "reviewed_by": "human", "approval_scope": "visual_plan_and_delivery",
                "revision": 1, "note": "已确认", "user_confirmation": "确认", "source": proposal, "artifacts": [proposal]})
            current = copy.deepcopy(old)
            current["revision_locks"] = {"previous_receipt": receipt, "user_confirmation": "采用修正，继续制作",
                "changes": [{"semantic_row_id": "r1", "segment_id": "s1", "component_id": "scene",
                             "candidate_id": "a"}]}
            with patch.object(selection, "discover_candidates", return_value=pool), \
                 patch.object(motion_capabilities, "overlay_candidates", return_value=[]):
                current_treatment = {**copy.deepcopy(old_treatment), "skill_selection": current}
                result = selection.assign_skills(ROOT, current, job_dir=job, director=director, treatment=current_treatment)
                # A global diversity solve would select a/b; the approved revision is a/a.
                self.assertEqual([a["candidate_id"] for a in result["assignments"]], ["a", "a"])
                changed = copy.deepcopy(current)
                changed["beats"][0]["required_change"] = "修改了无关项"
                with self.assertRaisesRegex(ValueError, "unaffected"):
                    selection.assign_skills(ROOT, changed, job_dir=job, director=director,
                                            treatment={**current_treatment, "skill_selection": changed})
                changed = copy.deepcopy(current)
                changed["revision_locks"]["changes"][0]["candidate_id"] = "missing"
                with self.assertRaisesRegex(ValueError, "not reviewed and feasible"):
                    selection.assign_skills(ROOT, changed, job_dir=job, director=director,
                                            treatment={**current_treatment, "skill_selection": changed})
                changed = copy.deepcopy(current)
                changed["beats"][0]["binding_snapshot"] = {"source": "不同的绑定"}
                with self.assertRaisesRegex(ValueError, "unaffected"):
                    selection.assign_skills(ROOT, changed, job_dir=job, director=director,
                                            treatment={**current_treatment, "skill_selection": changed})
                changed = copy.deepcopy(current)
                changed["fixed_context"][0]["source_ref"] = "另一个素材"
                with self.assertRaisesRegex(ValueError, "fixed material"):
                    selection.assign_skills(ROOT, changed, job_dir=job, director=director,
                                            treatment={**current_treatment, "skill_selection": changed})
                altered_director = copy.deepcopy(director)
                altered_director["segments"][0]["bindings"]["scene"] = {"source": "另一个绑定"}
                with self.assertRaisesRegex(ValueError, "component or binding"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                for field, value in (("start", 3 + 1 / 24), ("end", 5 + 1 / 24),
                                     ("visual_intent", {"statement": "另一个意思"})):
                    altered_director = copy.deepcopy(director)
                    altered_director["segments"][1][field] = value
                    with self.subTest(changed_row_field=field), self.assertRaisesRegex(
                            ValueError, "confirmed time or semantic intent"):
                        selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                                treatment=current_treatment)
                altered_treatment = copy.deepcopy(current_treatment)
                altered_treatment["semantic_lists"]["broll"][1]["components"][0]["segment_id"] = "s0"
                with self.assertRaisesRegex(ValueError, "confirmed row's segments"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=director,
                                            treatment=altered_treatment)
                altered_director = copy.deepcopy(director)
                altered_director["segments"][1]["visible_text"] = ["不同文字"]
                with self.assertRaisesRegex(ValueError, "unapproved segment field"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                # Explicit text edits keep their exact target and increment the
                # actual segment input version; other edits remain locked.
                director["segments"][1]["strategy_revision"] = 1
                write("old/director.json", director)
                director_ref = confirmation._record(job, job / "old/director.json")
                source = confirmation._read(job / "old/proposal.json")
                source["inputs"]["director"] = director_ref
                proposal = write("old/proposal.json", source)
                source_receipt = confirmation._read(job / receipt["path"])
                source_receipt.update(source=proposal, artifacts=[proposal])
                receipt = write(receipt["path"], source_receipt)
                current["revision_locks"]["previous_receipt"] = receipt
                revised = copy.deepcopy(director)
                revised["segments"][1].update(visible_text=["转向能力优先"], strategy_revision=2)
                scoped = copy.deepcopy(current)
                scoped["revision_locks"]["changes"][0]["segment_changes"] = {
                    "visible_text": ["转向能力优先"], "strategy_revision": 2}
                scoped_treatment = {**current_treatment, "skill_selection": scoped}
                self.assertEqual([a["candidate_id"] for a in selection.assign_skills(
                    ROOT, scoped, job_dir=job, director=revised, treatment=scoped_treatment)["assignments"]], ["a", "a"])
                revised["segments"][1]["visible_text"] = ["未获确认的文字"]
                with self.assertRaisesRegex(ValueError, "explicit text and strategy"):
                    selection.assign_skills(ROOT, scoped, job_dir=job, director=revised,
                                            treatment=scoped_treatment)
                altered_director = copy.deepcopy(director)
                altered_director["segments"][1]["visual_strategy"]["composition"]["avatar"]["position"] = "center"
                with self.assertRaisesRegex(ValueError, "unapproved presentation or avatar"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                altered_director = copy.deepcopy(director)
                altered_director["segments"][1]["visual_strategy"]["components"].append(
                    {"component_id": "rogue", "kind": "code_generated"})
                with self.assertRaisesRegex(ValueError, "unapproved visual component"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                altered_director = copy.deepcopy(director)
                altered_director["segments"][1]["visual_strategy"]["composition"]["family"] = "hybrid"
                with self.assertRaisesRegex(ValueError, "unapproved composition"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                altered_director = copy.deepcopy(director)
                altered_director["segments"][1]["visual_strategy"]["rationale"] = "偷换创作意图"
                with self.assertRaisesRegex(ValueError, "unapproved visual strategy field"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=altered_director,
                                            treatment=current_treatment)
                with self.assertRaisesRegex(ValueError, "numbering scope"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=director,
                                            treatment={**current_treatment, "numbering_scope_id": "new"})
                changed_treatment = copy.deepcopy(current_treatment)
                changed_treatment["semantic_lists"]["overlay"].append(
                    changed_treatment["semantic_lists"]["broll"].pop(0))
                with self.assertRaisesRegex(ValueError, "semantic rows or numbering"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=director,
                                            treatment=changed_treatment)
                new_treatment = write("new/treatment.json", current_treatment)
                new_proposal = write("new/proposal.json", {"kind": confirmation.SCHEMA, "job_id": "revision-job",
                    "inputs": {"treatment": new_treatment, "director": director_ref},
                    "numbering_scope_id": "scope", "numbering": {"r0": 1, "r1": 2, "r2": 3},
                    "provider_config_sha256": config["sha256"],
                    "rows": [{"semantic_row_id": "r" + str(i), "segment_id": "s" + str(i),
                              "component_id": "scene"} for i in range(3)]})
                new_receipt = {"source_schema": confirmation.SCHEMA, "job_id": "revision-job", "job_dir": str(job),
                    "stage": "visual_direction", "passed": True, "reviewed_by": "human",
                    "approval_scope": "visual_plan_and_delivery", "revision": 2, "note": "已确认",
                    "user_confirmation": "另一个决定", "source": new_proposal, "artifacts": [new_proposal]}
                write("manifests/local-qa-visual_direction-r2.json", new_receipt)
                with self.assertRaisesRegex(ValueError, "latest visual confirmation"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=director, treatment=current_treatment)
                new_receipt["user_confirmation"] = "采用修正，继续制作"
                write("manifests/local-qa-visual_direction-r2.json", new_receipt)
                self.assertEqual([a["candidate_id"] for a in selection.assign_skills(
                    ROOT, current, job_dir=job, director=director, treatment=current_treatment)["assignments"]], ["a", "a"])
                (job / "old/proposal.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "confirmed visual evidence changed"):
                    selection.assign_skills(ROOT, current, job_dir=job, director=director, treatment=current_treatment)



class PlanningOnlyChecksTest(unittest.TestCase):
    """Use real catalog/matching/assignment and temporary approved word inputs."""
    def test_selected_design_is_copied_and_changes_require_reassignment(self):
        from edit.hd.tools import motion_capabilities as motion
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            draft,treatment=self.make_plan(root,8)
            assignment=treatment['skill_selection']['assignments'][0]
            chosen=next(c for c in treatment['skill_selection']['beats'][0]['candidates']
                        if c['candidate_id']==assignment['candidate_id'])
            self.assertEqual(assignment['design_plan'],chosen['design_plan'])
            chosen['design_plan']['finish']='改成有纸张层次的当前设计方案。'
            self.assertNotEqual(assignment['design_plan'],chosen['design_plan'])
            result=motion.check_planning_only(ROOT,draft,treatment,job_dir=root)
            self.assertEqual(result['status'],'fail')
            self.assertIn('assignments changed',result['failures'][0]['reason'])

    def make_plan(self, root, seconds):
        from edit.hd.tools import contract_artifacts as artifacts, motion_capabilities as motion, motion_match_cache
        words = [{"text": "十二项测试对象", "start": 0.1, "end": 2.8}]
        workflow = {"stages": {}}
        for stage, rel, value in (
            ("speech_cleanup", "05-speech-cleanup/word-transcript.json", {"version": 1, "words": words}),
            ("edit_structure", "06-edit-structure/timeline-map.json", {"segments": [{
                "source_start": 0, "source_end": seconds, "timeline_start": 0, "timeline_end": seconds}]}),
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            artifacts.write_json_artifact(path, value)
            workflow["stages"][stage] = {"status":"approved", "artifacts":[{
                "path": rel, "sha256":artifacts.sha256_file(path), "bytes":path.stat().st_size}]}
        artifacts.write_json_artifact(root / "workflow.json", workflow)
        draft = {"segments": [{"segment_id":"s", "start":0, "end":seconds,
            "visual_strategy":{"mode":"single", "composition":{"family":"single_full_frame"},
                "components":[{"component_id":"c", "kind":"code_generated", "layer_role":"base"}]}}]}
        refs = [{"segment_id":"s", "component_id":"c"}]
        row = {"row_id":"number", "start_word":0, "end_word":1, "quote":words[0]["text"],
            "semantic":"真实数值强调", "visual_task":"展示十二项测试对象", "components":refs}
        treatment = {"semantic_lists":{"overlay":[], "broll":[row]},
            "beat_sheet":[{"start_word":0, "end_word":1, "quote":words[0]["text"],
                "decision":"broll", "visual":"数值强调", "components":refs}],
            "motion_queries":[{**refs[0], "tags":["数字与单位", "显现", "旧新"]}]}
        treatment = motion_match_cache.match_once(ROOT, draft, treatment)
        catalog = {r["candidate_id"]:r for r in motion.load_catalog(ROOT)}
        candidates = []
        for match in treatment["motion_matches"]["number"]["matches"]:
            cid = match["candidate_id"]
            fit = ("preferred" if cid == "eian-riso-broll:number" else
                   "equivalent" if cid == "eian-riso-broll:versus" else
                   "needs_adapter" if catalog[cid]["status"] != "supported" else "unsuitable")
            candidates.append({"candidate_id":cid, "fit":fit, "rejection_basis":"semantic",
                "design_plan":{"composition":"数值和单位共同成为主体。","typography":"主数值高于辅助说明。",
                               "finish":"用完整数字排版和细线图形。","focus":"当前数值显现后稳定阅读。"},
                "constraint_refs":{"requirement":"semantic","capability":"summary"},
                "reason":"独立规划夹具，数值强调优先，旧新为未选备选。", "visual_pattern":cid})
        pool = selection.discover_candidates(ROOT)
        reviews = {r["skill_id"]:{"fit":"equivalent" if r["skill_id"] == "eian-riso-broll" else "unsuitable",
            "reason":"本夹具只选真实数值入口。"} for r in pool}
        treatment["skill_selection"] = {"schema_version":1, "history_note":"synthetic planning only",
            "recent_context":[], "fixed_context":[], "overlay_beats":[], "beats":[{
                **refs[0], "semantic_row_id":"number", "start":0, "end":seconds,
                "single_source_review":{"decision":"keep","reason":"夹具保留Riso数值与旧新两个具体合格入口。"},
                "transcript":row["quote"], "semantic_goal":row["semantic"],
                "required_change":row["visual_task"], "candidates":candidates, "skill_reviews":reviews}]}
        treatment["skill_selection"] = selection.assign_skills(ROOT, treatment["skill_selection"])
        return draft, treatment

    def test_read_only_planning_passes_without_bindings_but_not_production(self):
        from edit.hd.tools import motion_capabilities as motion
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft, treatment = self.make_plan(root, 4)
            before = {str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = motion.check_planning_only(ROOT, draft, treatment, job_dir=root)
            self.assertEqual(result["status"], "pass", result)
            self.assertEqual(result["semantic_summary"], {"overlay_count":0, "broll_count":1})
            self.assertIn("visual_acceptance", result["not_run"])
            self.assertFalse(result["source_plans_modified"])
            self.assertEqual(before, {str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()})
            with self.assertRaises((KeyError, ValueError)):
                motion.check_offline_plan(ROOT, draft, treatment, job_dir=root)

    def test_selected_native_floor_is_current_and_unselected_floor_does_not_block(self):
        from edit.hd.tools import motion_capabilities as motion
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for seconds in (3, 3.99):
                with self.assertRaisesRegex(ValueError, "no timing-feasible candidate"):
                    self.make_plan(root, seconds)
            draft, treatment = self.make_plan(root, 4)
            result = motion.check_planning_only(ROOT, draft, treatment, job_dir=root)
            self.assertEqual(result["status"], "pass", result)  # Unselected versus needs 6.5 seconds.

    def test_missing_clock_is_not_verified_and_late_word_is_reported_first(self):
        from edit.hd.tools import motion_capabilities as motion
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft, treatment = self.make_plan(root, 4)
            result = motion.check_planning_only(ROOT, draft, treatment)
            self.assertEqual(result["status"], "needs_review", result)
            self.assertEqual(result["not_verified"][0]["check"], "approved_word_clock")
            draft["segments"][0]["start"] = 0.75
            for checker in (motion.check_planning_only, motion.check_offline_plan):
                result = checker(ROOT, draft, treatment, job_dir=root)
                self.assertEqual(result["status"], "fail", result)
                self.assertIn("number", result["failures"][0]["reason"])
                self.assertIn("word span", result["failures"][0]["reason"])


class PartialCandidateReviewTest(unittest.TestCase):
    """Use the real joint solver; pending candidates never become approvals."""

    def fixture(self, *, second_channel="B", pending_channel="C", pending_minimum=None):
        def native(cid, channel, template, **extra):
            return {"candidate_id": cid, "skill_id": channel, "template_id": template,
                    "role": "native", "status": "supported", "entrypoint": "entry",
                    "adapter_module": "motion_native_skill_adapter", "limitations": [], **extra}
        self.pool = [native("a", "A", "one"), native("b", second_channel, "two"),
                     native("pending", pending_channel, "three",
                            min_duration_seconds=pending_minimum)]
        design = {key: "具体主体、内容和本句动作" for key in
                  ("composition", "typography", "finish", "focus")}
        def beat(sid, start, choices):
            return {"segment_id": sid, "component_id": "scene", "semantic_row_id": sid,
                    "start": start, "end": start + 2, "window_status": "resolved",
                    "transcript": "本句", "semantic_goal": "说明", "required_change": "变化",
                    "skill_reviews": {c["skill_id"]: {"fit": "unreviewed", "reason": "保留待评渠道"}
                                      for c in self.pool},
                    "candidates": [{"candidate_id": cid, "fit": fit, "reason": "本次具体结论",
                                    **({"visual_pattern": cid, "design_plan": copy.deepcopy(design)}
                                       if fit == "equivalent" else {})} for cid, fit in choices]}
        source = {"schema_version": 1, "history_note": "独立离线样本", "beats": [
            beat("s0", 0, [("a", "equivalent")]),
            beat("s1", 2, [("b", "equivalent"), ("pending", "unreviewed")])],
            "overlay_beats": []}
        director = {"segments": [{"segment_id": b["segment_id"], "start": b["start"], "end": b["end"],
            "visual_strategy": {"composition": {"family": "single_full_frame"},
                                "components": [{"component_id": "scene"}]}} for b in source["beats"]]}
        return source, director

    def assign(self, source, director):
        with patch.object(selection, "discover_candidates", return_value=self.pool), \
             patch("edit.hd.tools.motion_capabilities.overlay_candidates", return_value=[]):
            return selection.assign_skills(ROOT, source, director=director)

    def test_equal_bounds_keep_unreviewed_and_never_select_it(self):
        source, director = self.fixture()
        before = copy.deepcopy(source)
        result = self.assign(source, director)
        self.assertEqual([c["candidate_id"] for c in result["assignments"]], ["a", "b"])
        self.assertEqual(result["beats"], before["beats"])
        self.assertEqual(source, before)
        self.assertEqual(result["diversity_review"]["reviewed_optimum"], [2, 2])
        self.assertEqual(result["diversity_review"]["optimistic_upper_bound"], [2, 2])
        source["beats"][1]["candidates"][0].pop("design_plan")
        with self.assertRaisesRegex(ValueError, "design_plan"):
            self.assign(source, director)

    def test_channel_and_template_gaps_both_stop_assignment(self):
        for second_channel, template in (("A", "one"), ("A", "two")):
            source, director = self.fixture(second_channel=second_channel,
                                           pending_channel="C" if template == "one" else "A")
            self.pool[1]["template_id"] = "one"
            self.pool[2]["template_id"] = template
            with self.subTest(template=template), self.assertRaisesRegex(ValueError, "unreviewed.*maximum"):
                self.assign(source, director)

    def test_current_windows_filter_both_bounds_and_are_recomputed(self):
        source, director = self.fixture(second_channel="A", pending_minimum=3)
        self.pool[1]["template_id"] = "one"
        result = self.assign(source, director)
        self.assertEqual(result["diversity_review"]["optimistic_upper_bound"], [1, 1])
        source["beats"][1]["end"] = director["segments"][1]["end"] = 5
        # A previously successful proof cannot authorize a changed window.
        source["diversity_review"] = result["diversity_review"]
        with self.assertRaisesRegex(ValueError, "unreviewed.*maximum"):
            self.assign(source, director)

    def test_unresolved_mismatched_fractional_and_overlapping_windows_stop(self):
        for case in ("unresolved", "director", "mismatch", "fractional", "overlap"):
            source, director = self.fixture()
            if case == "unresolved":
                source["beats"][0].pop("window_status")
            elif case == "director":
                director = None
            elif case == "mismatch":
                director["segments"][0]["end"] = 1
            elif case == "fractional":
                source["beats"][0]["end"] = director["segments"][0]["end"] = 1.01
            else:
                source["beats"][1]["start"] = director["segments"][1]["start"] = 1
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "window|director|overlap|24fps"):
                self.assign(source, director)

    def test_overlays_participate_and_real_native_clock_limits_apply(self):
        source, director = self.fixture(second_channel="A", pending_channel="B")
        self.pool[1]["template_id"] = "one"
        overlay = {**self.pool[1], "candidate_id": "overlay:known", "skill_id": "B",
                   "template_id": "overlay-template", "role": "aroll_overlay"}
        self.pool[2]["template_id"] = "overlay-template"
        beat = copy.deepcopy(source["beats"][0])
        beat.update(segment_id="o", semantic_row_id="o", start=4, end=6,
                    candidates=[{**beat["candidates"][0], "candidate_id": overlay["candidate_id"]}])
        source["overlay_beats"] = [beat]
        director["segments"].append({"segment_id": "o", "start": 4, "end": 6,
            "visual_strategy": {"composition": {"family": "aroll_with_overlay"},
                                "components": [{"component_id": "scene"}]}})
        # Unknown B cannot add a channel once a real overlay already supplies B.
        with patch.object(selection, "discover_candidates", return_value=self.pool), \
             patch("edit.hd.tools.motion_capabilities.overlay_candidates", return_value=[overlay]):
            result = selection.assign_skills(ROOT, source, director=director)
        self.assertEqual(result["diversity_review"]["reviewed_optimum"], [2, 2])
        from edit.hd.tools.motion_capabilities import overlay_candidates
        hw = next(c for c in overlay_candidates(ROOT) if c["candidate_id"] == "overlay:hw-pipeline")
        self.assertIsNotNone(selection.timing_failure(hw, {"segment_id": "o", "start": 0, "end": 2}))
        self.assertIsNone(selection.timing_failure(hw, {"segment_id": "o", "start": 0, "end": 3}))

    def test_actual_native_minimum_maximum_and_fixed_clocks(self):
        from edit.hd.tools.motion_capabilities import load_catalog
        catalog = load_catalog(ROOT)
        for module, minimum, maximum in (
                ("huashu_motion_adapter", 2, 20), ("riso_native_adapter", None, 20),
                ("lemo_wake_adapter", 1 / 24, 60), ("upstream_scene_adapter", 1 / 24, 60),
                ("doudou_adapter", 1 / 24, 60), ("talkcraft_native_adapter", 1 / 24, 60),
                ("whiteboard_adapter", 1 / 24, 60), ("paper_collage_adapter", 1 / 24, 60),
                ("hyperframes_notification_adapter", 14, 14), ("huashu_stat_adapter", 41 / 24, None)):
            row = next(c for c in catalog if c.get("adapter_module") == module)
            def failure(seconds):
                return selection.timing_failure(row, {"segment_id": "s", "start": 0, "end": seconds}, strict=True)
            with self.subTest(module=module):
                if minimum is not None:
                    if minimum > 1 / 24:
                        self.assertIsNotNone(failure(minimum - 1 / 24))
                    self.assertIsNone(failure(max(minimum, row.get("min_duration_seconds") or 0)))
                if maximum is not None:
                    self.assertIsNone(failure(maximum))
                    self.assertIsNotNone(failure(maximum + 1 / 24))
        row = next(c for c in catalog if c.get("adapter_module") == "lemo_wake_adapter")
        broken = copy.deepcopy(row)
        broken['adapter_module'] = 'unknown_clock_adapter'
        with self.assertRaisesRegex(ValueError, 'timing|clock'):
            selection.timing_failure(broken, {"segment_id": "s", "start": 0, "end": 3}, strict=True)
        broken.pop('adapter_module')
        with self.assertRaisesRegex(ValueError, 'timing|clock'):
            selection.timing_failure(broken, {"segment_id": "s", "start": 0, "end": 3}, strict=True)

    def test_complete_list_confirmation_passes_the_current_director(self):
        from edit.hd.tools import motion_match_cache, motion_capabilities, visual_confirmation
        source, director = self.fixture()
        source = self.assign(source, director)
        for beat, segment in zip(source['beats'], director['segments']):
            beat['binding_snapshot'] = {}
            segment['bindings'] = {'scene': {}}
            segment['visual_strategy']['components'][0]['kind'] = 'ai_generated'
        cached = {(b['segment_id'], 'scene'): {'matches': [{'candidate': c} for c in self.pool]}
                  for b in source['beats']}
        with patch.object(selection, 'discover_candidates', return_value=self.pool), \
             patch.object(motion_capabilities, 'overlay_candidates', return_value=[]), \
             patch.object(motion_match_cache, 'validate_reviews', return_value=cached), \
             patch.object(visual_confirmation, 'planned_generation_targets', return_value=set()):
            visual_confirmation._validate_template_choices(SimpleNamespace(job_dir=ROOT), director,
                                                           {'skill_selection': source})


if __name__ == "__main__":
    unittest.main()

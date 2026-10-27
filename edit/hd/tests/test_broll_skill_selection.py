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
        self.assertEqual(motion.search_capabilities(ROOT,
            "完全不相关的海边日落宠物散步", use="broll", catalog=catalog), [])
        self.assertEqual(motion.search_capabilities(ROOT,
            "精致 浅暖色 人物", use="broll", catalog=catalog), [])
        matches = motion.search_capabilities(ROOT, "方格逐格染色 比例", use="broll", catalog=catalog)
        grid = next(row for row in matches if row["candidate_id"].endswith("/unit-grid-proportion"))
        self.assertIn("方格逐格染色", grid["matched_dimensions"]["actions"])
        stage = next(row for row in catalog if row["candidate_id"].endswith("/stage-keyframe-tour"))
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
        self.assertEqual(len([cid for cid in by_id if cid.startswith("hd-talking-head-talkcraft:")]), 108)
        self.assertEqual(len([cid for cid in by_id if cid.startswith("overlay:")]), 8)
        self.assertEqual(by_id["history:local-canonical/process-relations"]["status"], "excluded")
        self.assertEqual(by_id["unconnected:hyperframes/strikethrough-replace"]["status"], "needs_adapter")
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
                draft, treatment = self.make_plan(root, seconds)
                self.assertNotIn("min_duration_seconds", treatment["motion_matches"]["number"]["matches"][0])
                result = motion.check_planning_only(ROOT, draft, treatment, job_dir=root)
                self.assertEqual(result["status"], "fail", result)
                self.assertIn("needs at least 4", result["failures"][0]["reason"])
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


if __name__ == "__main__":
    unittest.main()

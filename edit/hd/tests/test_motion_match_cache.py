"""Real catalog retrieval is cached, including after semantic coverage additions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from edit.hd.tools import motion_capabilities as motion, motion_match_cache as cache

ROOT = Path(__file__).resolve().parents[3]
DESIGN = {"composition": "主体置中，变化区域与说明在同一视觉范围。",
          "typography": "主标签与辅助信息分级，保留清楚的字形。",
          "finish": "使用细线和平面色块形成完整工具界面。",
          "focus": "当前对象变化时，其余对象保持稳定。"}


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        self.add_item("overlay", "并列要点", ["并列", "要点", "累积", "列表"])
        self.add_item("broll", "比较两种方案", ["对比", "前后", "方案"])

    def add_item(self, use, text, tags):
        index = len(self.director["segments"])
        sid = f"s{index}"
        self.director["segments"].append({"segment_id": sid,
            "visual_strategy": {"composition": {"family": "aroll_with_overlay" if use == "overlay" else "single_full_frame"},
                "components": [{"component_id": "c", "kind": "code_generated",
                                "layer_role": "annotation" if use == "overlay" else "base"}]}})
        self.treatment["semantic_lists"][use].append({"row_id": f"r{index}",
            "start_word": index, "end_word": index + 1, "quote": text,
            "semantic": text, "visual_task": text, "components": [{"segment_id": sid, "component_id": "c"}]})
        self.treatment["motion_queries"].append({"segment_id": sid, "component_id": "c", "tags": tags})

    def test_business_questions_recall_complete_authors_without_art_keywords(self):
        catalog = motion.load_catalog(ROOT)
        expected = {"gbro-collage-broll:gbro-collage-broll/design",
                    "paper-collage-hyperframes:paper-collage-ad/hyperframes",
                    "lemo-opuscar:lemo-opuscar/midcentury-toon",
                    "openfilm-motion-graphics:motion-graphics",
                    "muyang-flat-animation:muyang-flat-animation/design"}
        fixed = {"whiteboard-video:whiteboard-svg-blocks",
                 "doudou-remotion-whiteboard:doudou-reviewed-scene",
                 "paper-collage-ad:paper-collage-layer-animation",
                 "video-talkcraft:line-chart-story-draw"}
        for quote in ("临期货先撤哪排？", "冷柜不制冷先保哪批？", "收银堵了怎么分流？"):
            with self.subTest(quote=quote):
                matches = motion.search_capabilities(ROOT, quote, use="broll", catalog=catalog)
                ids = {r["candidate_id"] for r in matches}
                self.assertTrue(expected <= ids, sorted(expected - ids))
                self.assertFalse(fixed & ids)
                for row in matches:
                    self.assertEqual(row["recall_basis"], "full_scene_authoring")
                    self.assertFalse(row["has_motion_basis"])
                    self.assertTrue(row["semantic_review_required"])

    def test_authoring_recall_and_cache_use_the_same_evidence(self):
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        self.add_item("broll", "冷柜不制冷先保哪批？", ["冷柜", "失冷", "待决问题"])
        direct = motion.search_capabilities(ROOT, "冷柜 失冷 待决问题", use="broll")
        first = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, first)
        evidence = context[("s0", "c")]["matches"]
        fields = ("candidate_id", "matched_dimensions", "retrieval_score", "recall_basis")
        self.assertEqual([m["evidence"] for m in evidence],
                         [{k: row[k] for k in fields} for row in direct])
        self.assertTrue(evidence)
        altered = copy.deepcopy(first)
        altered["motion_matches"]["r0"]["matches"][0]["recall_basis"] = "semantic_motion"
        altered["motion_matches"]["r0"]["matches_sha256"] = motion.contract_artifacts.sha256_json(
            altered["motion_matches"]["r0"]["matches"])
        with self.assertRaisesRegex(ValueError, "recall basis"):
            cache.validate_matches(ROOT, self.director, altered)

    def test_matching_policy_change_invalidates_old_draft_cache(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        original = copy.deepcopy(first)
        version = first["motion_matches"]["r0"]["matching_policy_version"]
        with patch.object(motion, "MATCHING_POLICY_VERSION", version + 1), \
             patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                cache.validate_matches(ROOT, self.director, first)
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 2)
            cache.validate_matches(ROOT, self.director, updated)
            self.assertTrue(all(e["matching_policy_version"] == version + 1
                                for e in updated["motion_matches"].values()))
        self.assertEqual(first, original)

    def test_reviewed_source_only_update_reuses_cache_but_unreviewed_source_is_refused(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        index = motion.contract_artifacts.read_json_artifact(ROOT / motion.INDEX)
        ref = 'skill-development/hd-talking-head/scripts/lemo_wake_adapter.py'
        target = next(p for p in index['profiles'] if p['candidate_id'] == 'lemo-wake:wake')
        target['reviewed_sources'][ref] = 'a' * 64
        read = motion.contract_artifacts.read_json_artifact
        digest = motion.contract_artifacts.sha256_file
        with patch.object(motion.contract_artifacts, 'read_json_artifact',
                side_effect=lambda path: index if Path(path) == ROOT / motion.INDEX else read(path)):
            for operation in (cache.match_once, cache.validate_matches):
                with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValueError, 'source changed'):
                    operation(ROOT, self.director, first)
            with patch.object(motion.contract_artifacts, 'sha256_file',
                    side_effect=lambda path: 'a' * 64 if Path(path) == ROOT / ref else digest(path)), \
                 patch.object(motion, 'search_capabilities', side_effect=AssertionError('must reuse')):
                self.assertEqual(cache.match_once(ROOT, self.director, first), first)
                context = cache.validate_matches(ROOT, self.director, first)
                wake = next(m['candidate'] for m in context[('s1', 'c')]['matches']
                            if m['candidate']['candidate_id'] == 'lemo-wake:wake')
                self.assertEqual(wake['capability']['reviewed_sources'][ref], 'a' * 64)

    def test_all_other_catalog_fields_and_actual_matching_rules_invalidate_cache(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        rows = motion.load_catalog(ROOT)
        for field in ('tags', 'status', 'uses', 'template_id', 'summary', 'content_scope', 'producer_version'):
            altered = copy.deepcopy(rows)
            row = next(r for r in altered if r['candidate_id'] == 'lemo-wake:wake')
            if field == 'tags': row['capability']['tags']['actions'].append('新动作')
            elif field == 'uses': row['capability']['uses'].append('design')
            elif field == 'summary': row['capability']['summary'] += '新限制'
            elif field == 'content_scope': row['capability']['content_scope']['mode'] = 'fixed_action'
            else: row[field] += '-changed'
            with self.subTest(field=field), patch.object(motion, 'load_catalog', return_value=altered):
                with self.assertRaisesRegex(ValueError, 'identity changed'):
                    cache.validate_matches(ROOT, self.director, first)
        read = Path.read_text
        def changed_rules(path, *args, **kwargs):
            text = read(path, *args, **kwargs)
            return text.replace('score = sum(', 'score = 2 * sum(', 1) if path == Path(motion.__file__) else text
        with patch.object(Path, 'read_text', autospec=True, side_effect=changed_rules):
            self.assertNotEqual(cache._policy_identity(), first['motion_matches']['r0']['matching_policy_sha256'])
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                cache.validate_matches(ROOT, self.director, first)

    def test_legacy_cache_requires_evidence_instead_of_automatic_rebinding_or_search(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        previous = motion.load_catalog(ROOT)
        legacy = copy.deepcopy(first)
        for entry in legacy['motion_matches'].values():
            entry.pop('matching_policy_sha256')
            entry['catalog_sha256'] = motion.contract_artifacts.sha256_json(previous)
        original = copy.deepcopy(legacy)
        with patch.object(motion, 'search_capabilities', side_effect=AssertionError('must not search')):
            with self.assertRaisesRegex(ValueError, 'explicit.*rebinding'):
                cache.match_once(ROOT, self.director, legacy)
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                cache.validate_matches(ROOT, self.director, legacy)
            for value in (None, '', 17, 'A' * 64, 'a' * 63, 'g' * 64):
                damaged = copy.deepcopy(first)
                damaged['motion_matches']['r0']['matching_policy_sha256'] = value
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'explicit.*rebinding'):
                    cache.match_once(ROOT, self.director, damaged)
        self.assertEqual(legacy, original)
        changed = copy.deepcopy(first)
        changed['motion_matches']['r0']['matching_policy_sha256'] = '0' * 64
        with patch.object(motion, 'search_capabilities', wraps=motion.search_capabilities) as search:
            self.assertEqual(cache.match_once(ROOT, self.director, changed), first)
            self.assertEqual(search.call_count, 1)

    def test_content_scope_requires_current_evidence_and_preserves_fixed_boundaries(self):
        index = motion.contract_artifacts.read_json_artifact(ROOT / motion.INDEX)
        read = motion.contract_artifacts.read_json_artifact
        for case in ("mode", "evidence", "fixed_component", "alpha_use"):
            altered = copy.deepcopy(index)
            target = next(r for r in altered["profiles"]
                          if r["candidate_id"] == ("overlay:pin-board" if case == "fixed_component"
                                                  else "openfilm-motion-graphics:motion-graphics"))
            if case == "mode":
                target["content_scope"]["mode"] = "anything"
            elif case == "evidence":
                target["content_scope"]["evidence_ref"] = "unreviewed.md"
            elif case == "fixed_component":
                target["content_scope"]["mode"] = "full_scene"
            else:
                target["uses"].append("aroll_overlay")
            with self.subTest(case=case), patch.object(motion.contract_artifacts, "read_json_artifact",
                    side_effect=lambda path: altered if Path(path) == ROOT / motion.INDEX else read(path)):
                with self.assertRaisesRegex(ValueError, "scope"):
                    motion.load_profiles(ROOT)
        profiles = motion.load_profiles(ROOT)
        self.assertEqual(sum(cid.startswith("lemo-opuscar:") and
                             p["content_scope"]["mode"] == "full_scene" for cid, p in profiles.items()), 59)
        for cid in ("whiteboard-video:whiteboard-svg-blocks",
                    "doudou-remotion-whiteboard:doudou-reviewed-scene",
                    "paper-collage-ad:paper-collage-layer-animation",
                    "video-talkcraft:line-chart-story-draw"):
            self.assertEqual(profiles[cid]["content_scope"]["mode"], "fixed_action")
        self.assertTrue(any("真实本地纸素材" in v for v in
                            profiles["paper-collage-hyperframes:paper-collage-ad/hyperframes"]["limitations"]))

    def test_unchanged_and_new_items_match_only_once(self):
        before = copy.deepcopy(self.treatment)
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            first = cache.match_once(ROOT, self.director, self.treatment)
            self.assertEqual(search.call_count, 2)
            self.assertEqual(self.treatment, before)
            self.treatment = first
            self.add_item("overlay", "步骤提示", ["流程", "连线", "步骤"])
            updated = cache.match_once(ROOT, self.director, self.treatment)
            self.assertEqual(search.call_count, 3)
            self.assertEqual(updated["motion_matches"]["r0"], first["motion_matches"]["r0"])
            cache.validate_matches(ROOT, self.director, updated)
            self.assertEqual(search.call_count, 3)

    def test_split_keeps_one_semantic_item_and_reuses_matching(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        part = copy.deepcopy(self.director["segments"][0])
        part["segment_id"] = "split"
        self.director["segments"].append(part)
        first["semantic_lists"]["overlay"][0]["components"].append({"segment_id": "split", "component_id": "c"})
        first["motion_queries"].append({"segment_id": "split", "component_id": "c", "tags": first["motion_queries"][0]["tags"]})
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 0)
            context = cache.validate_matches(ROOT, self.director, updated)
        self.assertEqual(context[("split", "c")]["row_id"], "r0")

    def test_changed_semantics_update_only_that_item(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        first["semantic_lists"]["overlay"][0]["visual_task"] = "重新说明同一组并列要点"
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 1)
        self.assertEqual(updated["motion_matches"]["r1"], first["motion_matches"]["r1"])

    def test_corrupt_or_stale_caches_are_not_silently_accepted(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        self.assertTrue(first["motion_matches"]["r0"]["matches"])
        for case in ("absent", "catalog", "query", "duplicate", "evidence"):
            altered = copy.deepcopy(first)
            if case == "absent":
                altered.pop("motion_matches")
            elif case == "catalog":
                altered["motion_matches"]["r0"]["catalog_sha256"] = "0" * 64
            elif case == "query":
                altered["motion_queries"].pop()
            elif case == "duplicate":
                matches = altered["motion_matches"]["r0"]["matches"]
                matches.append(copy.deepcopy(matches[0]))
            else:
                altered["motion_matches"]["r0"]["matches"][0]["retrieval_score"] += 1
            with self.subTest(case=case), self.assertRaises(ValueError):
                cache.validate_matches(ROOT, self.director, altered)

    def test_trimmed_cache_is_rejected_even_with_a_recomputed_digest(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        entry = first['motion_matches']['r1']
        self.assertGreater(len(entry['matches']), 1)
        entry['matches'] = entry['matches'][:1]
        entry['matches_sha256'] = motion.contract_artifacts.sha256_json(entry['matches'])
        with patch.object(motion, 'search_capabilities', side_effect=AssertionError('must not search again')):
            with self.assertRaisesRegex(ValueError, 'complete recalled candidate set'):
                cache.validate_matches(ROOT, self.director, first)
            with self.assertRaisesRegex(ValueError, 'complete recalled candidate set'):
                cache.match_once(ROOT, self.director, first)

    def test_every_matched_candidate_requires_a_concrete_review(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, first)
        first["skill_selection"] = {"beats": [], "overlay_beats": []}
        for (sid, cid), item in context.items():
            beat = {"segment_id": sid, "component_id": cid, "semantic_row_id": item["row_id"],
                "candidates": [{"candidate_id": match["candidate"]["candidate_id"],
                    "fit": "equivalent" if match["candidate"]["status"] == "supported" else "needs_adapter",
                    "design_plan": copy.deepcopy(DESIGN),
                    "reason": "缓存与选择入口测试，实际内容另经原生输入检查"}
                    for match in item["matches"]]}
            beat['single_source_review'] = {'decision': 'keep', 'reason': '此测试保持当前缓存中全部合格候选，不按偏好删除。'}
            first["skill_selection"]["overlay_beats" if item["semantic"]["type"] == "贴片" else "beats"].append(beat)
        cache.validate_reviews(ROOT, self.director, first)
        first["skill_selection"]["overlay_beats"][0]["candidates"].pop()
        with self.assertRaisesRegex(ValueError, "every cached match"):
            cache.validate_reviews(ROOT, self.director, first)

    def test_unreviewed_cache_stays_complete_and_requires_current_joint_proof(self):
        from edit.hd.tools import broll_skill_selection as selection
        first = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, first)
        skills = {c['skill_id'] for c in selection.discover_candidates(ROOT)}
        first['skill_selection'] = {'schema_version': 1, 'history_note': '独立缓存回归',
                                    'beats': [], 'overlay_beats': []}
        for index, ((sid, cid), item) in enumerate(context.items()):
            segment = next(s for s in self.director['segments'] if s['segment_id'] == sid)
            segment.update(start=index * 4, end=index * 4 + 4)
            overlay = item['semantic']['type'] == '贴片'
            chosen = ('overlay:grid-card-assemble' if overlay else
                      'openfilm-motion-graphics:motion-graphics')
            beat = {'segment_id': sid, 'component_id': cid, 'semantic_row_id': item['row_id'],
                    'start': segment['start'], 'end': segment['end'], 'window_status': 'resolved',
                    'transcript': item['semantic']['quote'], 'semantic_goal': item['semantic']['semantic'],
                    'required_change': item['semantic']['visual_task'],
                    'skill_reviews': {skill: {'fit': 'unreviewed', 'reason': '保留尚未评审的渠道'}
                                      for skill in skills},
                    'single_source_review': {'decision': 'keep', 'reason': '保留所有候选；联合上下界相等。'},
                    'candidates': [{'candidate_id': m['candidate']['candidate_id'],
                                    'fit': 'equivalent' if m['candidate']['candidate_id'] == chosen else 'unreviewed',
                                    'reason': '本次逐项结论，未知项没有伪装通过。',
                                    **({'design_plan': copy.deepcopy(DESIGN), 'visual_pattern': chosen}
                                       if m['candidate']['candidate_id'] == chosen else {})}
                                   for m in item['matches']]}
            first['skill_selection']['overlay_beats' if overlay else 'beats'].append(beat)
        before = copy.deepcopy(first)
        with patch.object(motion, 'search_capabilities', side_effect=AssertionError('must not rematch')):
            cache.validate_reviews(ROOT, self.director, first)
        self.assertEqual(first, before)
        first['skill_selection']['beats'][0]['candidates'].pop()
        with self.assertRaisesRegex(ValueError, 'every cached match'):
            cache.validate_reviews(ROOT, self.director, first)

    def test_design_and_exclusion_evidence_gate_does_not_rematch(self):
        first = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, first)
        first['skill_selection'] = {'beats': [], 'overlay_beats': []}
        for (sid, cid), item in context.items():
            beat = {'segment_id': sid, 'component_id': cid, 'semantic_row_id': item['row_id'],
                'single_source_review': {'decision': 'keep', 'reason': '保留已召回且可用的原生候选。'},
                'candidates': [{'candidate_id': m['candidate']['candidate_id'],
                    'fit': 'equivalent' if m['candidate']['status'] == 'supported' else 'needs_adapter',
                    'reason': '合成测试的当前内容设计。', 'design_plan': copy.deepcopy(DESIGN)} for m in item['matches']]}
            first['skill_selection']['overlay_beats' if item['semantic']['type'] == '贴片' else 'beats'].append(beat)
        candidate = next(c for c in first['skill_selection']['beats'][0]['candidates'] if c['fit'] == 'equivalent')
        with patch.object(motion, 'search_capabilities', side_effect=AssertionError('must not rematch')):
            cache.validate_reviews(ROOT, self.director, first)
            for field in cache.DESIGN_FIELDS:
                bad = copy.deepcopy(first)
                target = next(c for c in bad['skill_selection']['beats'][0]['candidates'] if c['fit'] == 'equivalent')
                target['design_plan'].pop(field)
                with self.subTest(missing_design=field), self.assertRaisesRegex(ValueError, 'design_plan'):
                    cache.validate_reviews(ROOT, self.director, bad)
            candidate.update(fit='unsuitable', rejection_basis='semantic',
                             constraint_refs={'requirement': 'quote', 'capability': 'limitations/0'})
            cache.validate_reviews(ROOT, self.director, first)
            for refs in ({'requirement': 'visual_task', 'capability': 'limitations/0'},
                         {'requirement': 'quote', 'capability': 'other-candidate/limitations/0'},
                         {'requirement': 'quote', 'capability': 'limitations/9999'}):
                candidate['constraint_refs'] = refs
                with self.subTest(refs=refs), self.assertRaises(ValueError):
                    cache.validate_reviews(ROOT, self.director, first)
            candidate['constraint_refs'] = {'requirement': 'quote', 'capability': 'limitations/0'}
            candidate['rejection_basis'] = 'authorization'
            with self.assertRaisesRegex(ValueError, 'confirmed constraint'):
                cache.validate_reviews(ROOT, self.director, first)

    def test_single_source_requires_an_explicit_completed_review(self):
        from edit.hd.tools.broll_skill_selection import source_channel
        self.treatment = {'semantic_lists': {'overlay': [], 'broll': []}, 'motion_queries': []}
        self.director = {'segments': []}
        self.add_item('overlay', '想法经过AI继续推进', ['三步顺序', '连续协作'])
        # This scenario intentionally has one channel; new authoring channels
        # in the production catalog must not change that fixture assumption.
        catalog = [row for row in motion.load_catalog(ROOT) if source_channel(row['skill_id']) == 'hyperframes']
        with patch.object(motion, 'load_catalog', return_value=catalog):
            first = cache.match_once(ROOT, self.director, self.treatment)
            item = next(iter(cache.validate_matches(ROOT, self.director, first).values()))
            beat = {'segment_id': 's0', 'component_id': 'c', 'semantic_row_id': 'r0',
                'candidates': [{'candidate_id': m['candidate']['candidate_id'], 'fit': 'equivalent',
                    'reason': '保留原生三步连线能力。', 'design_plan': copy.deepcopy(DESIGN)} for m in item['matches']]}
            first['skill_selection'] = {'beats': [], 'overlay_beats': [beat]}
            with self.assertRaisesRegex(ValueError, 'single_source_review'):
                cache.validate_reviews(ROOT, self.director, first)
            beat['single_source_review'] = {'decision': 'revise', 'reason': '还需核对候选排除条件。'}
            with self.assertRaisesRegex(ValueError, 'single_source_review'):
                cache.validate_reviews(ROOT, self.director, first)
            beat['single_source_review']['decision'] = 'keep'
            cache.validate_reviews(ROOT, self.director, first)

    def test_selected_openfilm_design_reaches_existing_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'brief.json'
            brief = {'source_binding': {'segment_id': 'seg-001', 'start': 0, 'end': 2},
                     'creative_handoff': {'style_reason': '；'.join(DESIGN.values())}}
            path.write_text(json.dumps(brief), encoding='utf-8')
            director = {'segments': [{'segment_id': 'seg-001', 'start': 0, 'end': 2,
                         'bindings': {'visual': {'brief_sha256': motion.contract_artifacts.sha256_file(path)}}}]}
            treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'visual', 'brief_path': 'brief.json'}],
                'skill_selection': {'assignments': [{'segment_id': 'seg-001', 'component_id': 'visual',
                    'skill_id': 'openfilm-motion-graphics', 'design_plan': copy.deepcopy(DESIGN)}]}}
            cache.validate_design_handoffs(director, treatment, root)
            treatment['skill_selection']['assignments'][0]['design_plan']['finish'] = '改为纸张纹理，需要新的真实交接。'
            with self.assertRaisesRegex(ValueError, 'creative_handoff'):
                cache.validate_design_handoffs(director, treatment, root)

    def test_selected_lemo_handoff_rejects_changed_semantic_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            design = {"composition": "构图", "typography": "字形", "finish": "质感", "focus": "重点"}
            director = {"segments": [{"segment_id": "seg-001", "start": 0, "end": 2}]}
            row = {"row_id": "row-001", "start_word": 2, "end_word": 5,
                   "quote": "原话", "semantic": "目标", "visual_task": "变化",
                   "components": [{"segment_id": "seg-001", "component_id": "visual"}]}
            handoff = {"transcript": "原话", "semantic_goal": "目标", "required_change": "变化",
                       "visual_pattern": "模式", "design_plan": design}
            treatment = {"semantic_lists": {"overlay": [], "broll": [row]},
                         "skill_selection": {"beats": [{"segment_id": "seg-001", "component_id": "visual",
                             "semantic_row_id": "row-001", "start_word": 2, "end_word": 5,
                             "transcript": "原话", "semantic_goal": "目标", "required_change": "变化",
                             "visual_pattern": "模式", "design_plan": design}], "overlay_beats": [],
                             "assignments": [{"segment_id": "seg-001", "component_id": "visual",
                                 "skill_id": "lemo-opuscar", "template_id": "lemo-opuscar/blueprint",
                                 "visual_pattern": "模式", "design_plan": design}]}}
            with patch.object(cache.motion_capabilities, "_bound_brief",
                              return_value={"style_slug": "blueprint", "creative_handoff": handoff}):
                cache.validate_design_handoffs(director, treatment, root)
                bad = copy.deepcopy(treatment)
                bad["skill_selection"]["beats"][0]["transcript"] = "篡改"
                with self.assertRaisesRegex(ValueError, "semantic handoff"):
                    cache.validate_design_handoffs(director, bad, root)

    def test_confirmed_constraint_uses_existing_workflow_job_identity(self):
        from edit.hd.tools import visual_confirmation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'workflow.json').write_text(json.dumps({'job_id':'current-job'}))
            semantic={'row_id':'current-row','quote':'原话','semantic':'必须表达的变化'}
            beat={'segment_id':'seg-001','component_id':'visual','start':0,'end':3}
            candidate={'status':'supported','min_duration_seconds':5,'capability':{'limitations':['原生至少5秒。']}}
            receipt={'path':'manifests/existing-approval.json','sha256':'a'*64,'bytes':10}
            review={'rejection_basis':'timing','constraint_refs':{'requirement':{
                'source':'locked_window','receipt':receipt},'capability':'min_duration_seconds'}}
            row={'semantic_row_id':'current-row',**beat}
            with patch.object(visual_confirmation,'_validate_source',return_value=({}, {'rows':[row]})) as source:
                cache._constraint_refs(review,semantic,candidate,beat,job_dir=root)
                source.assert_called_once_with(root,receipt,job_id='current-job')
                for bad in ({**beat,'end':4},{**beat,'component_id':'another'}):
                    with self.subTest(beat=bad),self.assertRaises(ValueError):
                        cache._constraint_refs(review,semantic,candidate,bad,job_dir=root)
                candidate['min_duration_seconds']=2
                with self.assertRaisesRegex(ValueError,'unchanged window'):
                    cache._constraint_refs(review,semantic,candidate,beat,job_dir=root)
            with self.assertRaises(ValueError):
                cache._constraint_refs(review,semantic,candidate,beat,job_dir=root)

    def test_explicit_wake_opening_does_not_forge_motion_evidence(self):
        wake = "lemo-wake:wake"
        self.treatment["skill_selection"] = {"opening": {
            "segment_id": "s1", "component_id": "c", "candidate_id": wake}}
        self.treatment["motion_queries"][1]["tags"] = ["展示已批准封面"]
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            first = cache.match_once(ROOT, self.director, self.treatment)
            self.assertEqual(search.call_count, 2)
        matches = first["motion_matches"]["r1"]["matches"]
        wake_match = next(m for m in matches if m["candidate_id"] == wake)
        self.assertEqual(wake_match["recall_basis"], "full_scene_authoring")
        self.assertEqual(wake_match["matched_dimensions"]["actions"], [])
        cache.validate_matches(ROOT, self.director, first)
        self.assertEqual(cache.match_once(ROOT, self.director, first), first)

        # A real image-animation action can retrieve Wake through the same
        # public search path used by every other semantic item.
        first["motion_queries"][1]["tags"] = ["唤醒"]
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, first)
            self.assertEqual(search.call_count, 1)
        wake_match = next(m for m in updated["motion_matches"]["r1"]["matches"]
                          if m["candidate_id"] == wake)
        self.assertEqual(wake_match["recall_basis"], "semantic_motion")
        self.assertEqual(wake_match["matched_dimensions"]["actions"], ["唤醒"])
        cache.validate_matches(ROOT, self.director, updated)
        self.assertEqual(updated["motion_matches"]["r0"], first["motion_matches"]["r0"])


if __name__ == "__main__":
    unittest.main()

"""Real catalog retrieval is cached, including after semantic coverage additions."""
import copy
import hashlib
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


def expression_fixture(candidate, *, explanation="Use the fixture's reviewed visual slots."):
    sample_slots = {
        "adu-motion-video": ("/title", "前后对比"),
        "datamagic": ("/props/title", "榜单"),
        "eian-riso-broll": ("/data/mast/0", "数据说明"),
        "html-video": ("/props/data/title", "并列说明"),
        "huashu-motion-native": ("/metric/label", "累计"),
        "hyperframes": (("/labels/0", "三项待办") if "hw_pipeline" in candidate.get("entrypoint", "")
                         else ("/props/data/notifTitle", "原生通知")),
        "hypit-native-chat": ("/title", "变更通知"),
        "motion-graphics-native": ("/data/label", "原话重点"),
        "overlay-studio-native": ("/doc/cards/0/params/items", "并列要点"),
        "useanimations": ("/template_id", candidate.get("template_id", "useanimations/clock")),
        "wise-motion": ("/title", "跟踪说明"),
    }
    basis = {"capability": "summary", "explanation": explanation}
    slot = sample_slots.get(candidate.get("dependency_id"))
    if candidate.get("template_id") == "sweety-handdraw-video/web-kinetic-title":
        slot = ("/params/text", "并列要点")
    if slot:
        pointer, value = slot
        basis["content"] = {"visual_task": {pointer: value}}
    return basis


def bind_review_fixture(treatment, context):
    """The fixture explicitly completes its host review against these facts."""
    for beat in [*treatment['skill_selection'].get('beats', []),
                 *treatment['skill_selection'].get('overlay_beats', [])]:
        item = context[(beat['segment_id'], beat['component_id'])]
        row = item['semantic']
        beat.update(semantic_sha256=treatment['motion_matches'][item['row_id']]['semantic_sha256'],
                    transcript=row['quote'], semantic_goal=row['semantic'], required_change=row['visual_task'])
        catalog = {m['candidate']['candidate_id']: m['candidate'] for m in item['matches']}
        for review in beat['candidates']:
            if review['fit'] != 'unreviewed':
                candidate = catalog[review['candidate_id']]
                review['capability_sha256'] = cache.candidate_review_identity(candidate)
                if review['fit'] in {'preferred', 'equivalent'}:
                    review.setdefault('expression_basis', expression_fixture(candidate))


class HistoricalVisualExpressionTests(unittest.TestCase):
    def test_native_creative_handoffs_keep_the_same_readable_change(self):
        for number, quote, semantic, visual_task, dependency in (
            (4, "张汉生创业失败了好几次，", "张汉生多次创业受挫，次数未知。",
             "认得出创业尝试和反复受挫的关系。", "huashu-art-motion"),
            (12, "练熟了再拉小队放大，", "个人先练熟，再由小队扩大产出。",
             "看清个人练熟先达成，随后小队协作扩大产出。", "anidoodle"),
        ):
            with self.subTest(number=number):
                row = {"row_id": f"sem-{number:03}", "quote": quote, "semantic": semantic,
                       "visual_task": visual_task}
                candidate = {"dependency_id": dependency, "capability": {
                    "summary": "Original full-scene authoring", "editable_content": ["Subject and native action"]}}
                basis = {"capability": "editable_content/0", "explanation": visual_task}
                cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
                brief = {"task_source": {"semantic_row_id": row["row_id"], "quote": quote,
                    "semantic": semantic, "required_change": visual_task, "component_brief": "Original native scene"},
                    "native_options": ["native-stage-design"]}
                cache.validate_native_expression(brief, row, basis)
                brief["task_source"]["required_change"] = "画无字的叉或把卡片移到旁边。"
                with self.assertRaisesRegex(ValueError, "approved semantic row"):
                    cache.validate_native_expression(brief, row, basis)

    def test_team_count_cannot_stand_in_for_membership(self):
        row = {"row_id": "sem-008", "quote": "后来带着一支六人的远程小队，里面有宝妈，有前货车司机。",
               "semantic": "六人远程协作，成员中有宝妈和前货车司机。",
               "visual_task": "读出团队规模、远程协作和成员构成。",
               "required_content": {"team": {"meaning": "六人远程小队", "terms": ["6", "位"]},
                                    "members": {"meaning": "成员背景", "terms": ["宝妈", "前货车司机"]}}}
        candidate = {"dependency_id": "eian-riso-broll", "template_id": "eian-riso-broll/network", "capability": {
            "summary": "Network", "editable_content": ["Count, team context and group label"]}}
        basis = {"capability": "editable_content/0", "explanation": "大字显示人数，组说明承载两种成员身份。",
                 "content": {"team": {"/data/number": 6, "/data/unit": "位"}}}
        with self.assertRaisesRegex(ValueError, "every visible requirement"):
            cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        basis["content"]["members"] = {"/data/number": 6}
        with self.assertRaisesRegex(ValueError, "omits visible terms"):
            cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        basis["content"]["members"] = {"/data/say": "宝妈 · 前货车司机"}
        for pointer, value, failure in (
            ("/data/nodes", 6, "native content slots"),
            ("/data/number", 60, "omits visible terms"),
            ("/data/number", "6", "outside native capacity"),
        ):
            wrong = copy.deepcopy(basis)
            wrong["content"]["team"] = {pointer: value, "/data/unit": "位"}
            with self.subTest(pointer=pointer, value=value), self.assertRaisesRegex(ValueError, failure):
                cache._validate_expression_basis({"expression_basis": wrong}, row, candidate)
        cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        with self.assertRaisesRegex(ValueError, "changed approved content slot /data/say"):
            cache.validate_native_expression({"data": {"number": 6, "unit": "位", "say": "核心主创"}}, row, basis)
        actual = {"data": {"number": 6, "unit": "位", "say": "宝妈 · 前货车司机", "nodes": 6}}
        cache.validate_native_expression(actual, row, basis)
        actual["data"]["number"] = 60
        with self.assertRaisesRegex(ValueError, "changed approved content slot /data/number"):
            cache.validate_native_expression(actual, row, basis)

    def test_waiting_icon_needs_approved_visible_disambiguation(self):
        row = {"row_id": "sem-013", "quote": "不用等谁给机会。", "semantic": "机会不用等别人给。",
               "visual_task": "明示主动性，避免被理解为提醒等候。",
               "required_content": {"opportunity": {"meaning": "明确机会不用等",
                                                    "terms": ["机会", "不用等"]}}}
        candidate = {"dependency_id": "useanimations", "template_id": "useanimations/clock", "capability": {
            "summary": "Original clock", "editable_content": ["Native clock and optional short label"]}}
        basis = {"capability": "editable_content/0", "explanation": "标签澄清时钟只是等待概念。",
                 "content": {"opportunity": {"/template_id": "useanimations/clock"}}}
        with self.assertRaisesRegex(ValueError, "omits visible terms"):
            cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        english_label = copy.deepcopy(row)
        english_label["required_content"]["opportunity"]["terms"] = ["clock"]
        with self.assertRaisesRegex(ValueError, "omits visible terms"):
            cache._validate_expression_basis({"expression_basis": basis}, english_label, candidate)
        basis["content"]["opportunity"]["/labels/0/text"] = "机会不用等"
        cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        with self.assertRaisesRegex(ValueError, "missing approved content slot"):
            cache.validate_native_expression({"template_id": "useanimations/clock", "labels": []}, row, basis)
        cache.validate_native_expression({"template_id": "useanimations/clock",
                                          "labels": [{"text": "机会不用等", "start_frame": 0}]}, row, basis)

    def test_fixed_slots_check_value_type_length_and_index_before_selection(self):
        for dependency, route, pointer, value in (
            ("eian-riso-broll", {"template_id": "eian-riso-broll/network"},
             "/data/say", "宝妈和前货车司机都是核心主创"),
            ("eian-riso-broll", {"template_id": "eian-riso-broll/network"}, "/data/mast/2", "主创"),
            ("useanimations", {"template_id": "useanimations/clock"}, "/labels/99/text", "机会不用等"),
            ("useanimations", {"template_id": "useanimations/clock"}, "/labels/0/text", "机会不用一直等别人给"),
            ("datamagic", {}, "/props/rows/2/label", "第三行"),
            ("html-video", {}, "/props/data/items/0/value", 2.5),
        ):
            with self.subTest(pointer=pointer, value=value):
                candidate = {"dependency_id": dependency, "capability": {"summary": "Native content"}, **route}
                basis = {"capability": "summary", "explanation": "场景需要这个字段。",
                         "content": {"visual_task": {pointer: value}}}
                with self.assertRaisesRegex(ValueError, "capacity"):
                    cache._validate_expression_basis({"expression_basis": basis}, {"visual_task": "测试"}, candidate)

    def test_fixed_routes_reject_metadata_foreign_slots_and_conflicting_values(self):
        row = {"visual_task": "保留原生可见含义。"}
        for dependency, route, pointer, value in (
            ("datamagic", {}, "/props/rows/0/id", "宝妈"),
            ("useanimations", {}, "/labels/0/start_frame", 6),
            ("eian-riso-broll", {"template_id": "eian-riso-broll/shot"}, "/data/note/x", 6),
            ("eian-riso-broll", {"template_id": "eian-riso-broll/shot"}, "/data/slot", "宝妈"),
            ("eian-riso-broll", {"template_id": "eian-riso-broll/compare"}, "/data/say", "宝妈"),
            ("hyperframes", {"entrypoint": "scripts/render_hyperframes_hw_pipeline.cjs"},
             "/props/data/notifTitle", "宝妈"),
        ):
            with self.subTest(dependency=dependency, pointer=pointer):
                candidate = {"dependency_id": dependency, "capability": {"summary": "Native content"}, **route}
                basis = {"capability": "summary", "explanation": "可辨含义。",
                         "content": {"visual_task": {pointer: value}}}
                with self.assertRaisesRegex(ValueError, "native content slots"):
                    cache._validate_expression_basis({"expression_basis": basis}, row, candidate)

        row["required_content"] = {"x": {"meaning": "需要 A"}, "y": {"meaning": "也需要 B"}}
        candidate = {"dependency_id": "useanimations", "capability": {"summary": "Native icon with label"}}
        basis = {"capability": "summary", "explanation": "由短标补足含义。",
                 "content": {"x": {"/labels/0/text": "A"}, "y": {"/labels/0/text": "B"}}}
        with self.assertRaisesRegex(ValueError, "conflicts on native content slot"):
            cache._validate_expression_basis({"expression_basis": basis}, row, candidate)
        basis["content"]["y"]["/labels/0/text"] = "A"
        cache._validate_expression_basis({"expression_basis": basis}, row, candidate)

    def test_native_riso_input_must_match_selected_template(self):
        brief = {"schema_version": 1, "source_binding": {
            "aroll_sha256": "a" * 64, "segment_id": "seg-008", "start": 0, "end": 6},
            "composition": {"id": "team", "width": 1080, "height": 1920, "fps": 24, "frames": 144},
            "template_request": {"semantic_family": "collection_relationship", "information_units": 1,
                                 "numeric_values": [6], "numeric_scale": "linear"},
            "template": "network", "data": {"palette": "pal-teal", "mast": ["核心主创", "远程协作"],
                "number": 6, "comma": False, "unit": "位", "say": "宝妈 · 前货车司机", "nodes": 6, "duration": 6},
            "assets": []}
        candidate = {"role": "native", "adapter_module": "riso_native_adapter",
                     "dependency_id": "eian-riso-broll", "template_id": "eian-riso-broll/network"}
        self.assertEqual(motion._native_input_check(ROOT, candidate, brief)["status"], "pass")
        candidate["template_id"] = "eian-riso-broll/number"
        self.assertIn("selected native template", motion._native_input_check(ROOT, candidate, brief)["reason"])

    def test_native_hyperframes_input_must_match_selected_route(self):
        brief = {"schema_version": 2, "source_binding": {
            "aroll_sha256": "a" * 64, "segment_id": "seg-008", "start": 0, "end": 6},
            "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 144, "alpha": False},
            "template_request": {"semantic_family": "process_flow", "information_units": 2,
                                 "numeric_values": [], "numeric_scale": "not_applicable"},
            "entry": {"media_ref": "entry", "job_path": "scene.html", "scene_path": "index.html", "sha256": "b" * 64},
            "assets": [], "upstream_route": "hyperframes/chat-message",
            "source_pins": {"route": "hyperframes/chat-message", "sha256": "c" * 64}}
        candidate = {"role": "native", "adapter_module": "hyperframes_native_adapter",
                     "dependency_id": "hyperframes-native-adaptation",
                     "template_id": "hyperframes-chat-message-portrait-adaptation"}
        self.assertEqual(motion._native_input_check(ROOT, candidate, brief)["status"], "pass")
        candidate["template_id"] = "hyperframes-beat-timeline-portrait-adaptation"
        self.assertIn("selected upstream template", motion._native_input_check(ROOT, candidate, brief)["reason"])

    def test_requirement_query_is_stable_after_canonical_write(self):
        row = {"quote": "原话", "semantic": "团队角色", "visual_task": "认清关系",
               "required_content": {"z": {"meaning": "二"}, "a": {"meaning": "一"}}}
        reread = json.loads(cache.contract_artifacts.canonical_json_bytes(row))
        self.assertEqual(cache._query(row, ["角色"]), cache._query(reread, ["角色"]))


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

    def test_complete_overlay_pool_survives_missing_synonyms_and_uses_whole_task(self):
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        self.add_item("overlay", "多问一句：这条款，我真的看懂了吗？", ["条款", "看懂", "问题", "概念"])
        first = cache.match_once(ROOT, self.director, self.treatment)
        matches = first["motion_matches"]["r0"]["matches"]
        registered = motion.overlay_candidates(ROOT)
        self.assertEqual({m["candidate_id"] for m in matches}, {r["candidate_id"] for r in registered})
        self.assertEqual(len(matches), len(registered))
        notification = next(m for m in matches if m["candidate_id"] == "overlay:notification-stack")
        self.assertEqual(notification["recall_basis"], "same_use_review_required")
        self.assertFalse(notification["matched_dimensions"]["relations"])
        self.assertTrue(all("fit" not in match for match in matches))
        changed = copy.deepcopy(first)
        row = changed["semantic_lists"]["overlay"][0]
        row["semantic"] = "提醒观众自查是否看懂条款"
        row["visual_task"] = "让提醒弹出"
        with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
            updated = cache.match_once(ROOT, self.director, changed)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(search.call_args.args[1], cache._query(row, changed["motion_queries"][0]["tags"]))
            cache.validate_matches(ROOT, self.director, updated)
            cache.match_once(ROOT, self.director, updated)
            self.assertEqual(search.call_count, 1)
        reviewed_hint = next(m for m in updated["motion_matches"]["r0"]["matches"]
                             if m["candidate_id"] == "overlay:notification-stack")
        self.assertEqual(reviewed_hint["matched_dimensions"]["relations"], ["提醒"])
        self.assertNotEqual(first["motion_matches"]["r0"]["semantic_sha256"],
                            updated["motion_matches"]["r0"]["semantic_sha256"])

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
                self.assertTrue(fixed <= ids)
                for row in matches:
                    self.assertEqual(row["recall_basis"], "full_scene_authoring" if
                        row["capability"]["content_scope"]["mode"] == "full_scene" else "same_use_review_required")
                    self.assertFalse(row["has_motion_basis"])
                    self.assertTrue(row["semantic_review_required"])

    def test_authoring_recall_and_cache_use_the_same_evidence(self):
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        self.add_item("broll", "冷柜不制冷先保哪批？", ["冷柜", "失冷", "待决问题"])
        direct = motion.search_capabilities(ROOT, cache._query(
            self.treatment["semantic_lists"]["broll"][0], ["冷柜", "失冷", "待决问题"]), use="broll")
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
        ref = 'scripts/lemo_wake_adapter.py'
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
                             p["content_scope"]["mode"] == "full_scene" for cid, p in profiles.items()), 66)
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

    def test_explicit_visual_task_rebinding_preserves_recall_and_matches_only_additions(self):
        from edit.hd.tools import visual_confirmation as confirmation
        catalog = [{"candidate_id": "fixture:author", "status": "supported", "capability": {
            "uses": ["aroll_overlay", "broll"], "reviewed_sources": {},
            "content_scope": {"mode": "full_scene"}, "tags": {key: [] for key in motion.TAG_FIELDS}}}]
        for index, segment in enumerate(self.director["segments"]):
            segment.update(start=index * 3, end=index * 3 + 3, content_item_ids=["item" + str(index)])
        with tempfile.TemporaryDirectory() as directory, patch.object(motion, "load_catalog", return_value=catalog):
            root = Path(directory).resolve()
            def write(name, value):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                motion.contract_artifacts.write_json_artifact(path, value)
                return confirmation._record(root, path)
            config = write("manifests/provider-config.json", {})
            def approved_source(director, treatment, version):
                prefix = "source/" + str(version) + "/"
                inputs = {"director": write(prefix + "director.json", director),
                          "treatment": write(prefix + "treatment.json", treatment)}
                proposal = write(prefix + "proposal.json", {"job_id": "local-cache-job",
                    "kind": confirmation.SCHEMA, "inputs": inputs,
                    "provider_config_sha256": config["sha256"]})
                receipt = write(prefix + "receipt.json", {"job_id": "local-cache-job", "job_dir": str(root),
                    "source_schema": confirmation.SCHEMA, "stage": "visual_direction", "passed": True,
                    "authorized_by": "user", "authorization_scope": "visual_plan_and_generation", "revision": version,
                    "note": "本次真实批准", "user_confirmation": "按该方案制作", "source": proposal,
                    "artifacts": [proposal]})
                mapping = write(prefix + confirmation.MAPPING, {"source_approval": receipt,
                    "proposal": proposal, "realization_inputs": inputs})
                write("workflow.json", {"job_id": "local-cache-job", "stages": {"visual_direction": {
                    "status": "needs_revision", "artifacts": [], "lineage": [mapping]}}})
                return receipt
            first = cache.match_once(ROOT, self.director, self.treatment)
            context = cache.validate_matches(ROOT, self.director, first)
            first['skill_selection'] = {'beats': [], 'overlay_beats': [],
                'assignments': [{'segment_id': 's1', 'component_id': 'c', 'candidate_id': 'fixture:author'}],
                'overlay_assignments': [{'segment_id': 's0', 'component_id': 'c', 'candidate_id': 'fixture:author'}],
                'diversity_review': {'reviewed_optimum': [1, 1]}}
            for (sid, cid), item in context.items():
                beat = {'segment_id': sid, 'component_id': cid, 'semantic_row_id': item['row_id'],
                    'candidates': [{'candidate_id': 'fixture:author', 'fit': 'equivalent',
                                    'reason': 'Explicit fixture review', 'design_plan': copy.deepcopy(DESIGN)}]}
                first['skill_selection']['overlay_beats' if item['semantic']['type'] == '贴片' else 'beats'].append(beat)
            bind_review_fixture(first, context)
            before = copy.deepcopy(first)
            receipt = approved_source(self.director, first, 1)
            current = copy.deepcopy(first)
            current["semantic_lists"]["overlay"][0]["visual_task"] = "将分类标签替换为当前主题"
            current["semantic_lists"]["overlay"][0]["semantic"] = "补足当前主题的成员身份"
            current["semantic_lists"]["overlay"][0]["required_content"] = {
                "members": {"meaning": "让观众辨认成员身份"}}
            current["skill_selection"]["revision_locks"] = {"previous_receipt": receipt,
                "user_confirmation": "不要出现任务示意，换一些内容显示", "changes": [{
                    "semantic_row_id": "r0", "segment_id": "s0", "component_id": "c", "candidate_id": "fixture:author"}]}
            with patch.object(motion, "search_capabilities", side_effect=AssertionError("must not search old rows")):
                rebound, changed = cache.rebind_local_visual_tasks(ROOT, self.director, current, job_dir=root)
                self.assertEqual(changed, ["r0"])
                self.assertEqual(first, before)
                self.assertEqual(rebound["motion_matches"]["r1"], first["motion_matches"]["r1"])
                expected = copy.deepcopy(first["motion_matches"]["r0"])
                expected["semantic_sha256"] = rebound["motion_matches"]["r0"]["semantic_sha256"]
                self.assertEqual(rebound["motion_matches"]["r0"], expected)
                self.assertEqual(rebound['skill_selection']['beats'], first['skill_selection']['beats'])
                self.assertEqual(rebound['skill_selection']['assignments'], first['skill_selection']['assignments'])
                self.assertEqual(rebound['skill_selection']['overlay_assignments'], [])
                self.assertNotIn('diversity_review', rebound['skill_selection'])
                self.assertEqual(rebound['skill_selection']['revision_locks'], current['skill_selection']['revision_locks'])
                reviewed = rebound['skill_selection']['overlay_beats'][0]
                self.assertNotIn('semantic_sha256', reviewed)
                self.assertEqual(reviewed['candidates'][0]['fit'], 'unreviewed')
                self.assertNotIn('design_plan', reviewed['candidates'][0])
                cache.validate_matches(ROOT, self.director, rebound)
                for case in ("tags", "quote", "other_row_semantic", "start_word", "end_word", "components",
                             "segment_clock", "source_clock", "cache", "instruction", "unrequested"):
                    bad, draft = copy.deepcopy(current), copy.deepcopy(self.director)
                    row = bad["semantic_lists"]["overlay"][0]
                    if case == "tags": bad["motion_queries"][0]["tags"].append("其他对象")
                    elif case == "quote": row[case] += "改变意思"
                    elif case == "other_row_semantic": bad["semantic_lists"]["broll"][0]["semantic"] += "未授权"
                    elif case in ("start_word", "end_word"): row[case] += 1
                    elif case == "components": row["components"][0]["component_id"] = "unknown"
                    elif case == "segment_clock": draft["segments"][0]["end"] += 1 / 24
                    elif case == "source_clock": bad["source_clock"] = {"duration": 99}
                    elif case == "cache": bad["motion_matches"]["r0"]["matches"] = []
                    elif case == "instruction": bad["skill_selection"].pop("revision_locks")
                    else: bad["skill_selection"]["revision_locks"]["changes"][0]["semantic_row_id"] = "r1"
                    with self.subTest(rejected=case), self.assertRaises(ValueError):
                        cache.rebind_local_visual_tasks(ROOT, draft, bad, job_dir=root)
            # The new approved baseline itself can contain an earlier rebind.
            # Follow its registered source, not older receipts in the directory.
            next_receipt = approved_source(self.director, rebound, 2)
            again = copy.deepcopy(rebound)
            again["semantic_lists"]["overlay"][0]["visual_task"] = "再改一次当前主题文字"
            again["skill_selection"]["revision_locks"]["previous_receipt"] = next_receipt
            with patch.object(motion, "search_capabilities", side_effect=AssertionError("must follow approved cache")):
                cache.rebind_local_visual_tasks(ROOT, self.director, again, job_dir=root)
                again["skill_selection"]["revision_locks"]["previous_receipt"] = receipt
                with self.assertRaisesRegex(ValueError, "current approved source"):
                    cache.rebind_local_visual_tasks(ROOT, self.director, again, job_dir=root)
            self.treatment = rebound
            self.add_item("overlay", "新增问题", ["问题", "待决"])
            with patch.object(motion, "search_capabilities", wraps=motion.search_capabilities) as search:
                updated = cache.match_once(ROOT, self.director, self.treatment)
                self.assertEqual(search.call_count, 1)
                self.assertEqual(search.call_args.args[1], cache._query(
                    self.treatment["semantic_lists"]["overlay"][-1], ["问题", "待决"]))
                for row_id in first["motion_matches"]:
                    self.assertEqual(updated["motion_matches"][row_id], rebound["motion_matches"][row_id])

    def test_explicit_visual_task_helper_does_not_change_matching_policy(self):
        path = Path(cache.__file__)
        source = path.read_text()
        helper = next(node for node in cache.ast.parse(source).body
                      if isinstance(node, cache.ast.FunctionDef) and node.name == "rebind_local_visual_tasks")
        lines = source.splitlines(keepends=True)
        without_helper = "".join(lines[:helper.lineno - 1] + lines[helper.end_lineno:])
        read = Path.read_text
        current = cache._policy_identity()
        with patch.object(Path, "read_text", autospec=True,
                side_effect=lambda target, *args, **kwargs: without_helper if target == path
                    else read(target, *args, **kwargs)):
            self.assertEqual(cache._policy_identity(), current)

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
        bind_review_fixture(first, context)
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
        bind_review_fixture(first, context)
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
        bind_review_fixture(first, context)
        candidate = next(c for c in first['skill_selection']['beats'][0]['candidates'] if c['fit'] == 'equivalent')
        with patch.object(motion, 'search_capabilities', side_effect=AssertionError('must not rematch')):
            cache.validate_reviews(ROOT, self.director, first)
            for field in cache.DESIGN_FIELDS:
                bad = copy.deepcopy(first)
                target = next(c for c in bad['skill_selection']['beats'][0]['candidates'] if c['fit'] == 'equivalent')
                target['design_plan'].pop(field)
                with self.subTest(unselected_design=field):
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
            bind_review_fixture(first, {('s0', 'c'): item})
            with self.assertRaisesRegex(ValueError, 'single_source_review'):
                cache.validate_reviews(ROOT, self.director, first)
            beat['single_source_review'] = {'decision': 'revise', 'reason': '还需核对候选排除条件。'}
            with self.assertRaisesRegex(ValueError, 'single_source_review'):
                cache.validate_reviews(ROOT, self.director, first)
            beat['single_source_review']['decision'] = 'keep'
            cache.validate_reviews(ROOT, self.director, first)

    def test_selected_openfilm_keeps_semantics_without_copying_parent_design(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'brief.json'
            brief = {'source_binding': {'segment_id': 'seg-001', 'start': 0, 'end': 2},
                     'creative_handoff': {'transcript': '原话', 'semantic_goal': '目标',
                         'required_change': '变化', 'style_reason': '原生自行设计的构图与材质'}}
            path.write_text(json.dumps(brief), encoding='utf-8')
            director = {'segments': [{'segment_id': 'seg-001', 'start': 0, 'end': 2,
                         'bindings': {'visual': {'dependency_id': 'openfilm-motion-graphics',
                             'template_id': 'openfilm/motion-graphics-scene',
                             'brief_sha256': motion.contract_artifacts.sha256_file(path)}}}]}
            treatment = {'scenes': [{'segment_id': 'seg-001', 'component_id': 'visual', 'brief_path': 'brief.json'}],
                'skill_selection': {'assignments': [{'segment_id': 'seg-001', 'component_id': 'visual',
                    'skill_id': 'openfilm-motion-graphics', 'template_id': 'openfilm/motion-graphics-scene',
                    'design_plan': copy.deepcopy(DESIGN)}], 'beats': [{'segment_id': 'seg-001',
                        'component_id': 'visual', 'semantic_row_id': 'row-001', 'transcript': '原话',
                        'semantic_goal': '目标', 'required_change': '变化'}]},
                'semantic_lists': {'broll': [{'row_id': 'row-001', 'quote': '原话', 'semantic': '目标',
                    'visual_task': '变化', 'components': [{'segment_id': 'seg-001', 'component_id': 'visual'}]}]}}
            cache.validate_design_handoffs(director, treatment, root)
            treatment['skill_selection']['assignments'][0]['design_plan']['finish'] = '改为纸张纹理，需要新的真实交接。'
            cache.validate_design_handoffs(director, treatment, root)
            treatment['skill_selection']['beats'][0]['transcript'] = '篡改'
            with self.assertRaisesRegex(ValueError, 'semantic handoff'):
                cache.validate_design_handoffs(director, treatment, root)

    def test_selected_lemo_handoff_rejects_changed_semantic_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            design = {"composition": "构图", "typography": "字形", "finish": "质感", "focus": "重点"}
            director = {"segments": [{"segment_id": "seg-001", "start": 0, "end": 2,
                "bindings": {"visual": {"dependency_id": "lemo-opuscar", "template_id": "lemo-opuscar/blueprint"}}}]}
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

    def test_authorization_exclusion_requires_missing_current_design_video_channel(self):
        from types import SimpleNamespace
        from edit.hd.tools import startup, state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = SimpleNamespace(job_dir=root)
            (root / "job-context.json").write_text("{}")
            manifests = root / "manifests"
            manifests.mkdir()
            path = manifests / "provider-config.json"
            approval = manifests / "setup-approval.json"
            config = {"generation_enabled": False, "providers": []}
            row = {"row_id": "row", "quote": "原话", "semantic": "任务"}
            beat = {"segment_id": "seg-001", "component_id": "visual"}
            design = {"role": "design", "capability": {"summary": "原生设计"}}
            review = {"rejection_basis": "authorization", "constraint_refs": {
                "requirement": {"source": "authorization", "receipt": {"path": "ordinary-approval.json"}},
                "capability": "summary"}}
            with self.assertRaisesRegex(ValueError, "current video channel evidence"):
                cache._constraint_refs(review, row, design, beat, job_dir=root)
            review["constraint_refs"]["requirement"] = {"source": "authorization", "purpose": "video"}
            with self.assertRaisesRegex(ValueError, "current video channel evidence"):
                cache._constraint_refs(review, row, {**design, "role": "native"}, beat, job_dir=root)

            def approve_config():
                payload = json.dumps(config).encode()
                path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                approval.write_text(json.dumps({"provider_config_sha256": digest}))
                return path, digest

            with patch.object(state, "load_job", return_value=job), \
                 patch.object(startup, "require_startup"), \
                 patch.object(startup, "_config", side_effect=lambda _: approve_config()):
                cache._constraint_refs(review, row, design, beat, job_dir=root)
                config.update(generation_enabled=True, providers=[{
                    "purpose": "video", "provider": "fixture", "model": "fixture-model", "endpoint_id": "fixture.video",
                    "connection_status": "verified", "quota_status": "available"}])
                with self.assertRaisesRegex(ValueError, "does not establish a missing video channel"):
                    cache._constraint_refs(review, row, design, beat, job_dir=root)

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


class ReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [{"candidate_id": "fixture:" + name, "skill_id": "fixture-" + name,
            "status": "supported", "entrypoint": name + ".py", "producer_version": "1",
            "template_id": name, "role": "native", "min_duration_seconds": 1,
            "capability": {"uses": ["aroll_overlay", "broll"], "summary": "Authored scene",
                "editable_content": ["label"], "limitations": ["One semantic action"],
                "reviewed_sources": {name + ".py": "a" * 64},
                "content_scope": {"mode": "full_scene"},
                "tags": {field: [] for field in motion.TAG_FIELDS}}} for name in ("a", "b")]
        self.addCleanup(patch.stopall)
        patch.object(motion, "load_catalog", side_effect=lambda _: copy.deepcopy(self.catalog)).start()
        self.director = {"segments": []}
        self.treatment = {"semantic_lists": {"overlay": [], "broll": []}, "motion_queries": []}
        for index, use in enumerate(("overlay", "broll")):
            sid = "s" + str(index)
            self.director["segments"].append({"segment_id": sid, "start": index * 4, "end": index * 4 + 4,
                "visual_strategy": {"composition": {"family": "aroll_with_overlay" if index == 0 else "single_full_frame"},
                    "components": [{"component_id": "c", "kind": "code_generated",
                                    "layer_role": "annotation" if index == 0 else "base"}]}})
            self.treatment["semantic_lists"][use].append({"row_id": "r" + str(index),
                "start_word": index, "end_word": index + 1, "quote": "原话" + str(index),
                "semantic": "原意" + str(index), "visual_task": "变化" + str(index),
                "components": [{"segment_id": sid, "component_id": "c"}]})
            self.treatment["motion_queries"].append({"segment_id": sid, "component_id": "c", "tags": ["初始标签"]})
        self.treatment = cache.match_once(ROOT, self.director, self.treatment)
        context = cache.validate_matches(ROOT, self.director, self.treatment)
        selection = self.treatment["skill_selection"] = {"beats": [], "overlay_beats": [],
            "assignments": [{"segment_id": "s1", "component_id": "c", "candidate_id": "fixture:a"}],
            "overlay_assignments": [{"segment_id": "s0", "component_id": "c", "candidate_id": "fixture:a"}],
            "diversity_review": {"reviewed_optimum": [2, 2]},
            "revision_locks": {"user_confirmation": "Keep authorized routes"}}
        for (sid, cid), item in context.items():
            beat = {"segment_id": sid, "component_id": cid, "semantic_row_id": item["row_id"],
                "start": next(s['start'] for s in self.director['segments'] if s['segment_id'] == sid),
                "end": next(s['end'] for s in self.director['segments'] if s['segment_id'] == sid),
                "skill_reviews": {r['skill_id']: {'fit': 'equivalent', 'reason': 'Explicit source review'}
                                  for r in self.catalog},
                "candidates": [{"candidate_id": m["candidate"]["candidate_id"], "fit": "equivalent",
                    "reason": "Explicit fixture review", "visual_pattern": "scene", "design_plan": copy.deepcopy(DESIGN)}
                    for m in item["matches"]]}
            selection["overlay_beats" if item["semantic"]["type"] == "贴片" else "beats"].append(beat)
        bind_review_fixture(self.treatment, context)

    def test_unchanged_reviews_and_retrieval_only_changes_are_preserved(self):
        before = copy.deepcopy(self.treatment)
        with patch.object(motion, "search_capabilities", side_effect=AssertionError("must reuse")):
            self.assertEqual(cache.match_once(ROOT, self.director, before), before)
        changed = copy.deepcopy(before)
        changed["motion_queries"][0]["tags"] = ["排序提示"]
        self.catalog[0]["capability"]["tags"]["actions"].append("排序提示")
        self.catalog[0]["capability"]["title"] = "Display title only"
        with patch.object(motion, "MATCHING_POLICY_VERSION", motion.MATCHING_POLICY_VERSION + 1):
            updated = cache.match_once(ROOT, self.director, changed)
            cache._validate_review_structure(ROOT, self.director, updated)
        self.assertEqual(updated["skill_selection"], before["skill_selection"])
        self.assertEqual(updated["motion_matches"]["r0"]["semantic_sha256"], before["motion_matches"]["r0"]["semantic_sha256"])

    def test_semantic_change_invalidates_only_its_row_without_signing_new_reviews(self):
        before = copy.deepcopy(self.treatment)
        self.treatment["semantic_lists"]["overlay"][0]["semantic"] = "相反的语义"
        with self.assertRaisesRegex(ValueError, "semantic fields"):
            cache.validate_review_identities(self.director, self.treatment, self.catalog)
        updated = cache.match_once(ROOT, self.director, self.treatment)
        selection = updated["skill_selection"]
        beat = selection["overlay_beats"][0]
        self.assertEqual(beat["semantic_goal"], "相反的语义")
        self.assertNotIn("semantic_sha256", beat)
        self.assertTrue(all(r["fit"] == "unreviewed" and "design_plan" not in r and "capability_sha256" not in r
                            for r in beat["candidates"]))
        self.assertTrue(all(r['fit'] == 'unreviewed' for r in beat['skill_reviews'].values()))
        self.assertEqual(selection["beats"], before["skill_selection"]["beats"])
        self.assertEqual(selection["assignments"], before["skill_selection"]["assignments"])
        self.assertEqual(selection["overlay_assignments"], [])
        self.assertNotIn("diversity_review", selection)
        self.assertEqual(selection["revision_locks"], before["skill_selection"]["revision_locks"])
        self.assertEqual(cache.match_once(ROOT, self.director, updated), updated)

    def test_capability_or_verified_source_change_invalidates_only_that_candidate(self):
        before = copy.deepcopy(self.treatment)
        for change in ("limitation", "source"):
            with self.subTest(change=change):
                altered = copy.deepcopy(self.catalog)
                if change == "limitation":
                    altered[0]["capability"]["limitations"].append("New capacity constraint")
                else:
                    altered[0]["capability"]["reviewed_sources"]["a.py"] = "b" * 64
                with patch.object(motion, "load_catalog", return_value=altered):
                    with self.assertRaisesRegex(ValueError, "capability identity"):
                        cache.validate_review_identities(self.director, before, altered)
                    updated = cache.match_once(ROOT, self.director, before)
                for group in ("beats", "overlay_beats"):
                    old = before["skill_selection"][group][0]
                    new = updated["skill_selection"][group][0]
                    self.assertEqual(new["semantic_sha256"], old["semantic_sha256"])
                    self.assertEqual(new["candidates"][0]["fit"], "unreviewed")
                    self.assertNotIn("capability_sha256", new["candidates"][0])
                    self.assertEqual(new["candidates"][1], old["candidates"][1])
                    self.assertEqual(new['skill_reviews']['fixture-a']['fit'], 'unreviewed')
                    self.assertEqual(new['skill_reviews']['fixture-b'], old['skill_reviews']['fixture-b'])

    def test_changed_window_reopens_only_the_previous_timing_exclusion(self):
        for timing_exclusion in (True, False):
            with self.subTest(timing_exclusion=timing_exclusion):
                treatment = copy.deepcopy(self.treatment)
                beat = treatment['skill_selection']['overlay_beats'][0]
                beat['single_source_review'] = {'decision': 'keep', 'reason': 'Existing semantic source review'}
                if timing_exclusion:
                    beat['candidates'][0].update(fit='unsuitable', rejection_basis='timing',
                        constraint_refs={'requirement': {'source': 'locked_window', 'receipt': {}},
                                         'capability': 'min_duration_seconds'})
                    beat['skill_reviews']['fixture-a'] = {'fit': 'unsuitable', 'reason': 'Previous short window'}
                self.director['segments'][0]['end'] = 5
                updated = cache.match_once(ROOT, self.director, treatment)
                selection = updated['skill_selection']
                new = selection['overlay_beats'][0]
                self.assertEqual(new['end'], 5)
                self.assertEqual(new['semantic_sha256'], beat['semantic_sha256'])
                self.assertEqual(new['candidates'][1], beat['candidates'][1])
                self.assertEqual(selection['overlay_assignments'], [])
                self.assertNotIn('diversity_review', selection)
                if timing_exclusion:
                    self.assertEqual(new['candidates'][0]['fit'], 'unreviewed')
                    self.assertNotIn('rejection_basis', new['candidates'][0])
                    self.assertEqual(new['skill_reviews']['fixture-a']['fit'], 'unreviewed')
                else:
                    self.assertEqual(new['candidates'], beat['candidates'])
                    self.assertEqual(new['skill_reviews'], beat['skill_reviews'])
                    self.assertEqual(new['single_source_review'], beat['single_source_review'])

    def test_missing_review_identity_is_rejected_and_never_automatically_signed(self):
        for missing in ("semantic_sha256", "capability_sha256"):
            bad = copy.deepcopy(self.treatment)
            beat = bad["skill_selection"]["overlay_beats"][0]
            (beat if missing == "semantic_sha256" else beat["candidates"][0]).pop(missing)
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "identity"):
                cache._validate_review_structure(ROOT, self.director, bad)
            updated = cache.match_once(ROOT, self.director, bad)
            first = updated["skill_selection"]["overlay_beats"][0]["candidates"][0]
            self.assertEqual(first["fit"], "unreviewed")
            self.assertNotIn("capability_sha256", first)

    def test_broll_source_summaries_follow_added_unavailable_and_removed_sources(self):
        extra = copy.deepcopy(self.catalog[0])
        extra.update(candidate_id='fixture:c', skill_id='fixture-c', template_id='c', entrypoint='c.py')
        extra['capability']['uses'] = ['broll']
        self.catalog.append(extra)
        updated = cache.match_once(ROOT, self.director, self.treatment)
        source_reviews = updated['skill_selection']['beats'][0]['skill_reviews']
        previous = self.treatment['skill_selection']['beats'][0]['skill_reviews']
        self.assertEqual(set(source_reviews), {'fixture-a', 'fixture-b', 'fixture-c'})
        self.assertEqual(source_reviews['fixture-c']['fit'], 'unreviewed')
        self.assertEqual({key: source_reviews[key] for key in previous}, previous)
        self.assertEqual(updated['skill_selection']['overlay_beats'], self.treatment['skill_selection']['overlay_beats'])
        # Unavailable candidates leave matching, while their discovered source
        # still needs its own summary to satisfy the real assignment contract.
        self.catalog[-1]['status'] = 'needs_adapter'
        unavailable = cache.match_once(ROOT, self.director, updated)
        self.assertIn('fixture-c', unavailable['skill_selection']['beats'][0]['skill_reviews'])
        self.assertNotIn('fixture:c', {r['candidate_id'] for r in unavailable['motion_matches']['r1']['matches']})
        self.catalog.pop()
        removed = cache.match_once(ROOT, self.director, unavailable)
        self.assertEqual(removed['skill_selection']['beats'][0]['skill_reviews'], previous)


class CatalogOperationTests(unittest.TestCase):
    def test_verified_operation_loads_once_and_returns_independent_catalogs(self):
        from edit.hd.tools import startup
        memo = {}
        rows = [{'candidate_id': 'channel:template', 'capability': {'tags': ['original']}}]
        with patch.object(startup, '_operation_cache', return_value=memo), \
             patch.object(motion, '_catalog_sources', return_value=()), \
             patch.object(motion, '_load_catalog', return_value=rows) as load:
            first = motion.load_catalog(ROOT)
            first[0]['capability']['tags'].append('caller mutation')
            second = motion.load_catalog(ROOT)
            self.assertEqual(second[0]['capability']['tags'], ['original'])
            second.clear()
            self.assertEqual(len(motion.load_catalog(ROOT)), 1)
        load.assert_called_once_with(ROOT)

    def test_unverified_or_invalidated_operation_uses_real_loader(self):
        from edit.hd.tools import startup
        memo, active = {}, [None]
        rows = [{'candidate_id': 'channel:template'}]
        with patch.object(startup, '_operation_cache', side_effect=lambda *_: active[0]), \
             patch.object(motion, '_catalog_sources', return_value=()), \
             patch.object(motion, '_load_catalog', return_value=rows) as load:
            motion.load_catalog(ROOT); motion.load_catalog(ROOT)
            self.assertEqual(load.call_count, 2)
            active[0] = memo
            motion.load_catalog(ROOT); motion.load_catalog(ROOT)
            self.assertEqual(load.call_count, 3)
            active[0] = None
            load.side_effect = ValueError('reviewed source changed')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                motion.load_catalog(ROOT)
            self.assertEqual(load.call_count, 4)

    def test_changed_sources_during_load_cannot_publish_a_cached_catalog(self):
        from edit.hd.tools import startup
        memo = {}
        with patch.object(startup, '_operation_cache', side_effect=[memo, None]), \
             patch.object(motion, '_catalog_sources', return_value=()), \
             patch.object(motion, '_load_catalog', return_value=[{'candidate_id': 'channel:template'}]):
            with self.assertRaisesRegex(ValueError, 'sources changed'):
                motion.load_catalog(ROOT)
        self.assertEqual(memo, {})

    def test_native_source_inventory_changes_cannot_reuse_the_catalog(self):
        from edit.hd.tools import startup
        from scripts import motion_native_skill_adapter as native
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            root = project / 'vendor/source'; root.mkdir(parents=True)
            (project / 'references').mkdir()
            source = root / 'scene.py'; source.write_text('original')
            other = root / 'other.py'; other.write_text('other')
            alias = root / 'alias.py'; alias.symlink_to(source.name)
            empty = root / 'node_modules/nested'; empty.mkdir(parents=True)
            inventory = json.dumps({
                'source_root': 'vendor/source', 'files': {'scene.py': 'source', 'other.py': 'other'},
                'symlinks': {'alias.py': source.name}})
            for name in ('fixture', 'anidoodle', 'sweety-handdraw-video'):
                (project / 'references' / f'{name}-native-source.json').write_text(inventory)
            (project / 'archives/sources').mkdir(parents=True)
            (project / 'archives/sources/index.json').write_text('{"repositories": []}')
            memo = {}
            with patch.object(native, 'SOURCES', {'fixture': ('fixture', 'commit', 'pin')}), \
                 patch.object(startup, '_operation_cache', return_value=memo), \
                 patch.object(motion, '_load_catalog', return_value=[]) as load:
                motion.load_catalog(project); motion.load_catalog(project)
                self.assertEqual(load.call_count, 1)
                source.write_text('changed')
                motion.load_catalog(project)
                self.assertEqual(load.call_count, 2)
                (empty / 'unregistered.py').write_text('added')
                motion.load_catalog(project)
                self.assertEqual(load.call_count, 3)
                alias.unlink(); alias.symlink_to(other.name)
                motion.load_catalog(project)
                self.assertEqual(load.call_count, 4)


if __name__ == "__main__":
    unittest.main()

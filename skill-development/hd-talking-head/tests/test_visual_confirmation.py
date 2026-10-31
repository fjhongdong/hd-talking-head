"""The user approves a proposal once; production binds and compiles afterwards."""
from __future__ import annotations
import copy
import sys
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env
import run_stage
from edit.hd.tests import test_visual_direction as fixture_api
from edit.hd.tools import avatar_profile, contract_artifacts as artifacts, state, visual_confirmation as vc

class VisualConfirmationTests(unittest.TestCase):
    def test_deferred_wake_binds_only_authorized_completed_image(self):
        from types import SimpleNamespace
        import hashlib
        import json
        from edit.hd.tools import generation_queue
        root = self.job.job_dir
        original = root / 'wake-original.png'; original.write_bytes(b'original')
        edited = root / 'wake-edited.png'; edited.write_bytes(b'edited')
        aroll = root / '06-edit-structure/edited-aroll.mp4'; aroll.parent.mkdir(exist_ok=True); aroll.write_bytes(b'aroll')
        original_ref = vc._record(root, original); edited_ref = vc._record(root, edited); aroll_ref = vc._record(root, aroll)
        key = ('seg-001', 'component-1')
        base = {'producer_type':'dependency', 'dependency_id':'lemo-wake', 'entrypoint':'scripts/lemo_wake_adapter.py',
                'producer_version':'2.0.0', 'template_id':'lemo-wake/wake', 'primary_renderer':'HTMLCanvas'}
        segment = {'segment_id':key[0], 'start':0, 'end':1, 'visual_strategy':{'components':[{'component_id':key[1]}]},
                   'bindings':{key[1]:base}}
        frozen = {'segments':[segment]}
        beat = {'segment_id':key[0], 'component_id':key[1], 'binding_snapshot':base, 'semantic_goal':'approved beat'}
        treatment = {'scenes':[{'segment_id':key[0], 'component_id':key[1]}],
                     'skill_selection':{'assignments':[{'segment_id':key[0], 'component_id':key[1],
                       'candidate_id':'lemo-wake:wake', 'design_plan':{'focus':'approved focus'}}], 'beats':[beat]}}
        brief = {'schema_version':1, 'job_id':self.job.job_id,
                 'source_binding':{'aroll_sha256':aroll_ref['sha256'], 'segment_id':key[0], 'start':0, 'end':1},
                 'image':{'job_path':edited_ref['path'],'sha256':edited_ref['sha256'],'byte_count':edited_ref['bytes']},
                 'purpose':'body', 'composition':{'width':1080,'height':1920,'fps':24,'frames':24},
                 'semantic_goal':'approved focus', 'template_request':{'semantic_family':'image-led',
                 'information_units':1,'numeric_values':[],'numeric_scale':'not_applicable'},
                 'result_record_path':'native-inputs/wake-result.json'}
        path = root / 'native-inputs/wake-brief.json'; path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(brief), encoding='utf-8')
        digest = artifacts.sha256_file(path)
        source_sha = artifacts.sha256_file(_env.PROJECT / 'skill-development/hd-talking-head/scripts/lemo_wake_adapter.py')
        module = vc._native_result_adapter('lemo-wake')
        bound = {**base, 'renderer_version':module.UPSTREAM_COMMIT, 'template_version':'2.0.0',
                 'template_origin':'custom_fallback','adaptation_level':'structural','source_entrypoint':base['entrypoint'],
                 'source_sha256':source_sha,'sample_sha256':'a'*64,'brief_sha256':digest,
                 'verification_id':hashlib.sha256((source_sha+digest).encode()).hexdigest(),
                 'semantic_families':['image-led'],'capacity':{'min_units':1,'max_units':1},
                 'invocation_record':{'argv':['python',base['entrypoint']],'status':'planned','exit_code':None,
                                      'template_request':brief['template_request']}}
        director = copy.deepcopy(frozen); director['segments'][0]['bindings'][key[1]] = bound
        actual = copy.deepcopy(treatment); actual['scenes'][0]['brief_path']='native-inputs/wake-brief.json'
        actual['skill_selection']['beats'][0]['binding_snapshot']=bound
        step = {'id':'image-step','segment_id':key[0],'component_id':key[1],'purpose':'image'}
        proposal = {'generation_steps':[step]}
        request = {'id':'edit','purpose':'image','tool':'image.tool','arguments':{'referenced_image_paths':[str(original)]},
                   'input_files':[original_ref]}
        plan = {'from_id':'original','request':request,'issue':'cropped','count':1}
        identity = {'provider':'fixture'}
        origin = {'status':'completed','request':{'id':'original','tool':'image.tool'},'authorization':{'source':'approved'},
                  'channel_identity':identity,'config_sha256':'config','completion_response':{'conclusion':'cropped',
                  'artifacts':[{'type':'image','path':str(original),'sha256':original_ref['sha256'],'bytes':original_ref['bytes']}]}}
        item = {'request':request,'status':'completed','retry_of':'original','plan_request_id':'original',
                'image_edit_plan':plan,'user_confirmation':'one approved edit','channel_identity':identity,'config_sha256':'config',
                'approved_plan_sha256':artifacts.sha256_json(plan),'completion_response':{'artifacts':[
                    {'type':'image','path':str(edited),'sha256':edited_ref['sha256'],'bytes':edited_ref['bytes']}]}}
        job = SimpleNamespace(job_id=self.job.job_id, stages={'edit_structure':{'status':'approved','artifacts':[aroll_ref]}})
        with mock.patch.object(vc,'planned_generation_targets',return_value={key}), \
             mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(vc,'validate_visual_authorization',return_value={'source':proposal}), \
             mock.patch.object(generation_queue,'status',return_value={'items':{'original':origin}}), \
             mock.patch.object(vc,'generation_item',return_value=('edit',item)), \
             mock.patch.object(vc,'validate_generation_request',return_value={'step':step}):
            normalized, normalized_treatment = vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual)
            self.assertEqual(normalized,frozen)
            self.assertEqual(normalized_treatment,treatment)
            for field, value in [('status','pending'),('user_confirmation',''),('approved_plan_sha256','0'*64)]:
                with self.subTest(field=field):
                    changed = {**item,field:value}
                    with mock.patch.object(vc,'generation_item',return_value=('edit',changed)):
                        with self.assertRaises(ValueError):
                            vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual)
            changed = copy.deepcopy(actual); changed['skill_selection']['beats'][0]['semantic_goal'] = 'different'
            with self.assertRaisesRegex(ValueError,'semantic beat'):
                vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,changed)
            for field, value, message in [('semantic_goal','different','semantic goal'),
                    ('source_binding',{**brief['source_binding'],'end':2},'source clock')]:
                modified = {**brief,field:value}
                if field == 'source_binding': modified['composition'] = {**brief['composition'], 'frames':48}
                path.write_text(json.dumps(modified),encoding='utf-8')
                changed_director = copy.deepcopy(director)
                changed_director['segments'][0]['bindings'][key[1]]['brief_sha256'] = artifacts.sha256_file(path)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError,message):
                    vc._normalize_prepared_wake(root,proposal,frozen,treatment,changed_director,actual)
            path.write_text(json.dumps(brief),encoding='utf-8')
            edited.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'completed image'):
                vc._normalize_prepared_wake(root,proposal,frozen,treatment,director,actual)

    def test_paper_crop_consumption_requires_approved_source_and_exact_bound_pixels(self):
        from PIL import Image
        root = self.job.job_dir
        source, cropped, provenance, entry = (root / name for name in ('paper-source.png', 'paper-crop.png', 'paper-provenance.json', 'paper-scene.html'))
        image = Image.new('RGBA', (8, 8), (10, 20, 30, 128))
        image.putpixel((3, 3), (200, 2, 4, 255))
        image.save(source)
        image.crop((2, 2, 6, 6)).save(cropped)
        original = vc._record(root, source)
        output_sha = artifacts.sha256_file(cropped)
        entry.write_text('<html><body><img src="paper-crop.png"></body></html>', encoding='utf-8')
        brief = {'entry': {'job_path': entry.name, 'sha256': artifacts.sha256_file(entry)},
                 'assets': [{'job_path': cropped.name, 'scene_path': cropped.name, 'sha256': output_sha}]}
        proof = {'source_images': {'cutouts': {'path': source.name, 'sha256': original['sha256']}},
                 'crops': [{'source': source.name, 'source_sha256': original['sha256'],
                            'crop': [2, 2, 6, 6], 'output': cropped.name, 'output_sha256': output_sha}]}
        def check(data, assets=None, approved=None):
            artifacts.write_json_artifact(provenance, data)
            return vc._paper_crop_sources(root, assets or brief, vc._record(root, provenance),
                                          approved if approved is not None else [original])
        self.assertEqual(check(proof), {original['sha256']})
        with self.assertRaisesRegex(ValueError, 'approved generated image'):
            check(proof, approved=[])
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(proof, assets={**brief, 'assets': []})
        not_used = copy.deepcopy(brief); not_used['assets'][0]['scene_path'] = 'not-used.png'
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(proof, assets=not_used)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['crop'] = [1, 1, 5, 5]
        with self.assertRaisesRegex(ValueError, 'pixels differ'):
            check(wrong)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['crop'] = [0, 0, 9, 9]
        with self.assertRaisesRegex(ValueError, 'bounds exceed'):
            check(wrong)
        wrong = copy.deepcopy(proof); wrong['crops'][0]['output_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'consumed asset'):
            check(wrong)

    def test_routing_distribution_separates_logical_counts_channels_and_repeats(self):
        rows = [
            {"row_id": "a:1", "semantic_row_id": "logical-a", "segment_id": "a", "component_id": "1",
             "type": "B-roll", "start": 0, "end": 2, "number": 1},
            {"row_id": "a:2", "semantic_row_id": "logical-a", "segment_id": "a", "component_id": "2",
             "type": "B-roll", "start": 2, "end": 3, "number": 1, "channel": "Paper"},
            {"row_id": "b:1", "semantic_row_id": "logical-b", "segment_id": "b", "component_id": "1",
             "type": "B-roll", "start": 3, "end": 4, "number": 2, "channel": "Paper",
             "visual_pattern": "说明", "selection_reason": "保持动作连续"},
            {"row_id": "c:1", "semantic_row_id": "logical-c", "segment_id": "c", "component_id": "1",
             "type": "贴片", "start": 4, "end": 5, "number": 3, "channel": "Overlay"},
        ]
        rows[0]["channel"] = "Lovart"
        summary, repeats = vc._routing_distribution(rows, {"skill_selection": {}})
        self.assertEqual(summary["B-roll"]["logical_count"], 2)
        self.assertEqual(summary["B-roll"]["channels"]["Lovart"]["count"], 1)
        self.assertEqual(summary["B-roll"]["channels"]["Paper"]["duration"], 2.0)
        self.assertEqual(summary["贴片"]["logical_count"], 1)
        self.assertTrue(any(item[0] == 1 and item[1] == 2 for item in repeats))

    def test_routing_distribution_unions_overlaps_and_skips_same_logical_repeat(self):
        rows = [
            {"row_id": "a:1", "semantic_row_id": "same", "segment_id": "a", "component_id": "1", "type": "B-roll", "start": 0, "end": 3, "number": 1, "channel": "Paper"},
            {"row_id": "a:2", "semantic_row_id": "same", "segment_id": "a", "component_id": "2", "type": "B-roll", "start": 2, "end": 4, "number": 1, "channel": "Paper"},
            {"row_id": "b:1", "semantic_row_id": "next", "segment_id": "b", "component_id": "1", "type": "B-roll", "start": 4, "end": 5, "number": 2, "channel": "Paper", "visual_pattern": "同动作", "template": "other-template"},
        ]
        rows[1]['visual_pattern'] = '同动作'
        summary, repeats = vc._routing_distribution(rows, {"skill_selection": {}})
        self.assertEqual(summary["B-roll"]["logical_count"], 2)
        self.assertEqual(summary["B-roll"]["channels"]["Paper"]["duration"], 5.0)
        self.assertEqual(len(repeats), 1)
        self.assertIn("同构图/动作", repeats[0][2])

    def test_routing_uses_actual_incoming_and_outgoing_physical_channels(self):
        def row(sid, logical, begin, end, number, channel):
            return {'row_id':sid+':v','semantic_row_id':logical,'segment_id':sid,'component_id':'v',
                    'type':'B-roll','start':begin,'end':end,'number':number,'channel':channel}
        rows=[row('a','one',0,2,1,'Lovart'),row('b','one',2,3,1,'Paper'),
              row('c','two',3,4,2,'Paper'),row('d','two',4,5,2,'OpenFilm'),
              row('e','three',4.5,6,3,'OpenFilm')]
        summary,repeats=vc._routing_distribution(rows,{'skill_selection':{}})
        self.assertEqual(summary['B-roll']['channels']['OpenFilm']['duration'],2)
        self.assertEqual([(r[0],r[1]) for r in repeats],[(1,2),(2,3)])
        self.assertIn('同渠道：Paper',repeats[0][2])
        self.assertIn('同屏重叠',repeats[1][2])

    def setUp(self):
        self.fixture = fixture_api.VisualDirectionSchemaV3Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.job = self.fixture.job
        self.fixture._write_brief(*avatar_profile.plan_avatar_policy(
            [fixture_api.draft_segment(("external_stock",))])["segments"])
        config = self.job.job_dir / "manifests/provider-config.json"
        config.parent.mkdir(exist_ok=True)
        artifacts.write_json_artifact(config, {"schema_version": 1, "providers": [],
            "max_concurrency": 1, "generation_enabled": False})
        self.treatment = self.fixture.root / "treatment.json"
        artifacts.write_json_artifact(self.treatment, {
            "numbering_scope_id": "scope-test",
            "semantic_lists": {"overlay": [], "broll": [{"row_id": "sem-broll-1", "start_word": 0,
                "end_word": 1, "quote": "实际剪后口播", "semantic": "资料解释", "visual_task": "展示资料",
                "components": [{"segment_id": "seg-001", "component_id": "component-1"}]}]},
            "beat_sheet": [{"start_word": 0, "end_word": 1, "quote": "实际剪后口播",
                            "decision": "broll", "visual": "资料画面承接口播",
                            "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
                            "reason": "用具体资料画面解释这句口播"}],
            "motion_queries": [{"segment_id": "seg-001", "component_id": "component-1",
                                "tags": ["approved visual explanation"]}], "overlay_selection": [],
            "skill_selection": {"schema_version": 1, "beats": [], "assignments": [],
                "fixed_context": [{"segment_id": "seg-001", "component_id": "component-1",
                                   "visual_pattern": "existing material", "source_ref": "asset-1", "skill_id": "Example Stock",
                                   "start": 0.0, "end": 3.0}],
                "recent_context": [], "history_note": "synthetic fixture"}})
        from edit.hd.tools import motion_match_cache
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        artifacts.write_json_artifact(self.treatment,
            motion_match_cache.match_once(_env.PROJECT, director, treatment))

    def prepare(self):
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                        return_value=[{"text": "实际剪后口播", "start": 0.0, "end": 3.0}]):
            return vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)

    def confirm(self):
        review = {k: copy.deepcopy(v) for k, v in run_stage._summary(self.job, "visual_direction").items()
                  if k in {"job_id", "job_dir", "stage", "revision", "artifacts"}}
        review.update(passed=True, note="synthetic host inspected the proposed content",
                      user_confirmation="synthetic approval of this exact complete list")
        return run_stage._review(self.job, "visual_direction", review)

    def test_new_proposal_requires_complete_beat_sheet(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment.pop("beat_sheet")
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "beat_sheet"):
            self.prepare()

    def test_new_proposal_requires_explicit_numbering_scope(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment.pop("numbering_scope_id")
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "numbering_scope_id"):
            self.prepare()

    def test_new_proposal_rejects_non_renderable_internal_segment_id(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director["segments"][0]["segment_id"] = "seg-102-followup"
        artifacts.write_json_artifact(self.fixture.brief, director)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not renderable"):
            self.prepare()
        self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))

    def test_numbering_scope_starts_new_universe(self):
        def approve(revision, scope, numbering):
            root = self.job.job_dir / "07-visual-confirmation" / f"history-{revision}"
            root.mkdir(parents=True, exist_ok=True)
            proposal_path = root / "proposal.json"
            proposal = {"job_id": self.job.job_id, "job_dir": str(self.job.job_dir),
                        "kind": vc.SCHEMA, "numbering_scope_id": scope,
                        "rows": [{"row_id": key, "semantic_row_id": key}
                                 for key in numbering], "numbering": numbering}
            artifacts.write_json_artifact(proposal_path, proposal)
            source = vc._record(self.job.job_dir, proposal_path)
            receipt = {"source_schema": vc.SCHEMA, "job_id": self.job.job_id,
                       "job_dir": str(self.job.job_dir), "stage": "visual_direction",
                       "passed": True, "reviewed_by": "human",
                       "approval_scope": "visual_plan_and_delivery", "revision": revision,
                       "source": source}
            artifacts.write_json_artifact(self.job.job_dir / "manifests" /
                                          f"local-qa-visual_direction-r{revision}.json", receipt)

        # Same scope inherits the sparse mapping, including a deleted number.
        approve(1, "scope-target", {"semantic-keep": 3, "semantic-deleted": 7})
        self.assertEqual(vc._prior_numbering(self.job, "scope-target"),
                         {"semantic-keep": 3, "semantic-deleted": 7})
        numbered = vc.number_visual_rows(
            [{"row_id": "physical-new", "semantic_row_id": "semantic-new"}],
            vc._prior_numbering(self.job, "scope-target"))
        self.assertEqual(numbered[0]["number"], 8)

        # A different scope is a new numbering universe, so the old 20 is ignored.
        approve(2, "scope-other", {"semantic-old": 20})
        self.assertEqual(vc._prior_numbering(self.job, "scope-new"), {})
        self.assertEqual(vc.number_visual_rows(
            [{"row_id": "physical-first", "semantic_row_id": "semantic-first"}],
            vc._prior_numbering(self.job, "scope-new"))[0]["number"], 1)

        # Historical scope-less approvals remain readable but never seed a new scope.
        approve(3, None, {"semantic-legacy": 99})
        self.assertEqual(vc._prior_numbering(self.job, "scope-new"), {})

    def test_missing_draft_version_blocks_before_proposal_or_generation(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director.pop("schema_version")
        artifacts.write_json_artifact(self.fixture.brief, director)
        with self.assertRaisesRegex(Exception, "BROLL_SCHEMA_UNSUPPORTED"):
            self.prepare()
        self.assertFalse((self.job.job_dir / vc.DIRECTORY).exists())

    def test_native_timing_failure_blocks_proposal_before_generation(self):
        before = copy.deepcopy(self.job.stages["visual_direction"])
        with mock.patch("edit.hd.tools.overlay_alignment.validate_treatment",
                        side_effect=ValueError("native clock differs")):
            with self.assertRaisesRegex(ValueError, "native clock differs"):
                self.prepare()
        self.assertEqual(self.job.stages["visual_direction"], before)
        self.assertFalse(list((self.job.job_dir / "07-visual-confirmation").glob("*/proposal.json")))

    def test_beat_sheet_rejects_gap_or_stale_quote(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["quote"] = "过期口播"
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "quote"):
            self.prepare()

    def test_beat_sheet_accepts_actual_full_frame_strategy(self):
        director = {"segments": [{"start": 0, "end": 3,
            "visual_strategy": {"mode": "none", "components": [],
                "composition": {"family": "no_broll", "presenter_mode": "full_frame"}}}]}
        treatment = {"beat_sheet": [{"start_word": 0, "end_word": 1,
            "quote": "开场", "decision": "aroll", "visual": "真人开场称呼",
            "components": [], "reason": "保留真人视线和称呼，建立交流"}]}
        speech = [{"text": "开场", "start": 0, "end": 2.5}]
        vc._validate_beat_sheet(treatment, director, speech)
        director["segments"][0]["visual_strategy"]["mode"] = "single"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "full-frame"):
            vc._validate_beat_sheet(treatment, director, speech)

    def test_beat_sheet_allows_continuous_parallel_components(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        director["segments"][0]["visual_strategy"]["components"].append(
            {"component_id": "component-2", "kind": "external_stock", "layer_role": "base"})
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"].append(
            {"segment_id": "seg-001", "component_id": "component-2"})
        treatment["beat_sheet"][0]["merge_reason"] = "两个并列画面共同承接同一段连续动作"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "实际剪后口播", "start": 0.0, "end": 3.0}])

    def test_reused_component_requires_merge_reason_on_each_beat(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "实际", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "剪后口播", "decision": "broll",
             "visual": "连续资料", "components": [{"segment_id": "seg-001", "component_id": "component-1"}],
             "merge_reason": "同一连续资料画面覆盖后半句"}]
        with self.assertRaisesRegex(vc.VisualConfirmationError, "reused"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "实际", "start": 0.0, "end": 1.0},
                                     {"text": "剪后口播", "start": 1.0, "end": 3.0}])
        treatment["beat_sheet"][0]["merge_reason"] = "同一连续资料画面覆盖前半句"
        vc._validate_beat_sheet(treatment, director,
                                [{"text": "实际", "start": 0.0, "end": 1.0},
                                 {"text": "剪后口播", "start": 1.0, "end": 3.0}])

    def test_beat_sheet_rejects_unknown_component_and_uncovered_time(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["beat_sheet"][0]["components"][0]["component_id"] = "missing"
        with self.assertRaisesRegex(vc.VisualConfirmationError, "unknown"):
            vc._validate_beat_sheet(treatment, director,
                                    [{"text": "实际剪后口播", "start": 0.0, "end": 3.0}])

    def test_proposal_precedes_compile_and_one_confirmation_completes_plan(self):
        proposal = self.prepare()
        self.assertFalse((self.job.job_dir / "07-visual-direction/visual-plan.json").exists())
        ready = self.confirm()
        self.assertIn("| 编号 | 时间 |", (proposal.parent / "visual-routing.md").read_text())
        numbered = vc.approved_numbered_rows(self.job)
        self.assertEqual([(row["row_id"], row["number"]) for row in numbered],
                         [("seg-001:component-1", 1)])
        self.assertEqual(ready["review_required"], "host")
        self.assertEqual(self.job.stages["visual_direction"]["status"], "ready_for_review")
        approval = vc.validate_visual_authorization(self.job)["artifact"]
        original = (self.job.job_dir / approval["path"]).read_bytes()
        result = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(result["status"], "approved")
        final = state.load_job(self.job.job_dir)
        checked = vc.validate_visual_authorization(final, require_realized=True)
        self.assertEqual(checked["artifact"], approval)
        self.assertEqual(vc.approved_numbered_rows(final), numbered)
        self.assertEqual(original, (self.job.job_dir / approval["path"]).read_bytes())
        self.assertTrue(proposal.exists())
        changed = artifacts.read_json_artifact(self.fixture.brief)
        changed["segments"][0]["visual_intent"]["statement"] = "unapproved change"
        with self.assertRaises(vc.VisualConfirmationError):
            vc.validate_realization_draft(final, changed, artifacts.read_json_artifact(self.treatment))

    def test_time_coverage_failure_returns_to_semantics_before_publication(self):
        from edit.hd.tools import motion_match_cache
        stock = fixture_api.draft_segment(("external_stock",), end=1.0)
        presenter = fixture_api.draft_segment((), segment_id="seg-002", start=1.0, end=3.0)
        director = {"schema_version": 3, "segments": [stock, presenter]}
        from edit.hd.tools import avatar_profile
        director["segments"] = avatar_profile.plan_avatar_policy(director["segments"])["segments"]
        artifacts.write_json_artifact(self.fixture.brief, director)
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["fixed_context"][0]["end"] = 1.0
        treatment["beat_sheet"] = [
            {"start_word": 0, "end_word": 1, "quote": "实际剪后口播", "decision": "broll", "visual": "展示资料",
             "components": [{"segment_id": "seg-001", "component_id": "component-1"}]},
            {"start_word": 1, "end_word": 2, "quote": "继续解释", "decision": "aroll", "visual": "真人解释",
             "components": [], "reason": "真人接着解释当前资料"}]
        treatment = motion_match_cache.match_once(_env.PROJECT, director, treatment)
        artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech", return_value=[
                {"text": "实际剪后口播", "start": 0.0, "end": 1.0},
                {"text": "继续解释", "start": 1.0, "end": 3.0}]):
            with self.assertRaisesRegex(vc.VisualConfirmationError, "time coverage.*affected semantic list"):
                vc.prepare_visual_confirmation(self.job, self.fixture.brief, self.treatment)
        self.assertFalse((self.job.job_dir / vc.DIRECTORY).exists())

    def test_selected_image_to_video_channel_reaches_realized_template(self):
        self._selected_generation_flow("local_path")

    def test_lovart_project_is_checked_before_freeze_with_future_image(self):
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                  "providers": [
                      {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image"},
                      {"purpose": "video", "provider": "Lovart", "model": "kling/kling-video-o1", "endpoint_id": "mcp__lovart__generate_video"}]}
        for provider in config["providers"]:
            provider.update(connection_status="verified", quota_status="available", reference_images=True,
                            native_9_16=True, silent_output=True)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json", {
            "schema_version": 1, "image": {"model_binding": {"mode": "fixed"}},
            "video": {"model_binding": {"mode": "argument", "parameter": "model"}}})
        treatment = artifacts.read_json_artifact(self.treatment)
        future = {"$step": "image", "output": 0}
        steps = [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "fixture image"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "fixture video", "first_frame": future}, "depends_on": ["image"]}]
        treatment["generation_plan"] = {"steps": steps}
        artifacts.write_json_artifact(self.treatment, treatment)
        with self.assertRaisesRegex(ValueError, "real project_id"):
            self.prepare()
        self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))
        steps[1]["arguments"]["project_id"] = "synthetic-project"
        artifacts.write_json_artifact(self.treatment, treatment)
        proposal = artifacts.read_json_artifact(self.prepare())
        self.assertEqual(proposal["generation_steps"][1]["arguments"]["first_frame"], future)
        self.assertFalse((self.job.job_dir / "generated-media").exists())

    def test_uploaded_image_and_normalized_video_reach_realized_template(self):
        self._selected_generation_flow("upload")

    def _review_creator(self, segment, treatment, candidate_id):
        """Synthetic creative judgement; matching and assignment remain real."""
        from edit.hd.tools import motion_match_cache, motion_capabilities, broll_skill_selection
        director = {"schema_version": 3, "segments": [segment]}
        treatment["skill_selection"]["fixed_context"] = []
        treatment = motion_match_cache.match_once(_env.PROJECT, director, treatment)
        catalog = {r["candidate_id"]: r for r in motion_capabilities.load_catalog(_env.PROJECT)}
        row = treatment["semantic_lists"]["broll"][0]
        candidates = []
        for match in treatment["motion_matches"][row["row_id"]]["matches"]:
            cid = match["candidate_id"]
            candidates.append({"candidate_id": cid, "fit": "preferred" if cid == candidate_id else "equivalent",
                "reason": "Synthetic candidate review for the phase-boundary fixture",
                "visual_pattern": "blue-scene", "design_plan": dict.fromkeys(
                    ("composition", "typography", "finish", "focus"), "Synthetic blue scene design")})
        eligible = {catalog[c["candidate_id"]]["skill_id"] for c in candidates}
        beat = {"segment_id": segment["segment_id"], "component_id": "component-1",
            "semantic_row_id": row["row_id"], "start": segment["start"], "end": segment["end"],
            "transcript": row["quote"], "semantic_goal": row["semantic"], "required_change": row["visual_task"],
            "intent_statement": segment["visual_intent"]["statement"],
            "component_brief": segment["visual_strategy"]["components"][0]["brief"],
            "binding_snapshot": copy.deepcopy(segment["bindings"]["component-1"]), "candidates": candidates,
            "skill_reviews": {sid: {"fit": "equivalent" if sid in eligible else "unsuitable",
                "reason": "Synthetic full-pool judgement for this fixture"}
                for sid in {r["skill_id"] for r in broll_skill_selection.discover_candidates(_env.PROJECT)}}}
        treatment["skill_selection"]["beats"] = [beat]
        treatment["skill_selection"] = broll_skill_selection.assign_skills(_env.PROJECT, treatment["skill_selection"])
        self.assertEqual(treatment["skill_selection"]["assignments"][0]["candidate_id"], candidate_id)
        return treatment

    def test_design_final_video_requires_its_own_image_input(self):
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 1,
            "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                "endpoint_id": "fixture." + purpose, "connection_status": "verified",
                "quota_status": "available", "reference_images": True, "native_9_16": True,
                "silent_output": True} for purpose in ("image", "video")]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1, **{purpose: {"model_binding": {"mode": "fixed"},
                "reference_mode": "local_path"} for purpose in ("image", "video")}})
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(("ai_generated",))])["segments"][0]
        segment["bindings"]["component-1"] = {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"][0]["tags"] = ["蓝色场景"]
        treatment = self._review_creator(segment, treatment,
            "muyang-flat-animation:muyang-flat-animation/design")
        director = {"schema_version": 3, "segments": [segment]}
        def step(sid, purpose, arguments, depends_on=()):
            return {"id": sid, "purpose": purpose, "segment_id": "seg-001", "component_id": "component-1",
                    "arguments": arguments, "depends_on": list(depends_on)}
        image = step("image", "image", {"prompt": "a blue scene"})
        earlier = step("earlier-video", "video", {"reference": {"$step": "image"}}, ["image"])
        frozen = self.job.job_dir / "frozen.png"
        frozen.write_bytes(b"synthetic frozen image input")
        frozen_ref = vc._record(self.job.job_dir, frozen)
        for case in ("unrelated_local_image", "ordering_only", "video_ancestor"):
            first = copy.deepcopy(earlier)
            final = step("final-video", "video", {"prompt": "text-only final"}, ["earlier-video"])
            if case == "unrelated_local_image":
                first = step("earlier-video", "video", {"reference": str(frozen)})
                first["input_files"] = [frozen_ref]
            elif case == "video_ancestor":
                final["arguments"]["reference"] = {"$step": "earlier-video"}
            treatment["generation_plan"] = {"steps": [image, first, final]}
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "needs its image input"):
                vc.planned_generation_targets(_env.PROJECT, director, treatment, job_dir=self.job.job_dir)
        for final in (step("video", "video", {"reference": {"$step": "image"}}, ["image"]),
                      {**step("video", "video", {"reference": str(frozen)}), "input_files": [frozen_ref]}):
            treatment["generation_plan"] = {"steps": [image, final]}
            self.assertEqual(vc.planned_generation_targets(_env.PROJECT, director, treatment,
                job_dir=self.job.job_dir), {("seg-001", "component-1")})

    def test_native_paper_future_image_is_confirmed_before_authoring(self):
        from edit.hd.tools import motion_capabilities
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 1,
            "providers": [{"purpose": "image", "provider": "fixture", "model": "image-model",
                "endpoint_id": "fixture.image", "connection_status": "verified", "quota_status": "available",
                "reference_images": True, "native_9_16": True, "silent_output": True}]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1, "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"}})
        segment = avatar_profile.plan_avatar_policy([fixture_api.draft_segment(("code_generated",))])["segments"][0]
        cid = "paper-collage-hyperframes:paper-collage-ad/hyperframes"
        candidate = next(r for r in motion_capabilities.load_catalog(_env.PROJECT) if r["candidate_id"] == cid)
        segment["bindings"]["component-1"] = {**{k: candidate[k] for k in
            ("dependency_id", "entrypoint", "producer_version", "template_id")},
            "producer_type": "dependency", "primary_renderer": "HyperFrames"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"][0]["tags"] = ["蓝色场景"]
        treatment["generation_plan"] = {"steps": [{"id": "paper-image", "purpose": "image",
            "segment_id": "seg-001", "component_id": "component-1", "arguments": {"prompt": "blue paper assets"}}]}
        treatment["motion_readability"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "targets": [], "no_critical_text_reason": "Synthetic scene has no critical text"}]
        treatment = self._review_creator(segment, treatment, cid)
        self.fixture._write_brief(segment)
        artifacts.write_json_artifact(self.treatment, treatment)
        director = {"schema_version": 3, "segments": [segment]}
        deferred = copy.deepcopy(treatment)
        deferred['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                           'pending_generation': True}]
        from edit.hd.tools import motion_readability
        with mock.patch.object(motion_readability, '_managed', return_value=True):
            motion_readability.validate_direction_contract(self.job, director, deferred, phase='planning')
            with self.assertRaisesRegex(ValueError, 'uncreated approved generation'):
                motion_readability.validate_direction_contract(self.job, director, deferred, phase='completed')
        for case in ("missing_step", "wrong_target", "wrong_route", "invented_image", "unfrozen_reference", "fixed_action"):
            invalid = copy.deepcopy(treatment)
            changed = copy.deepcopy(director)
            if case == "missing_step": invalid["generation_plan"]["steps"] = []
            elif case == "wrong_target": invalid["generation_plan"]["steps"][0]["component_id"] = "missing"
            elif case == "wrong_route": changed["segments"][0]["bindings"]["component-1"]["template_id"] = "wrong"
            elif case == "invented_image": invalid["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": "missing.png"}]
            elif case == "unfrozen_reference": invalid["generation_plan"]["steps"][0]["arguments"]["referenced_image_paths"] = ["/missing.png"]
            else: invalid["skill_selection"]["assignments"][0]["candidate_id"] = "eian-riso-broll:focus"
            with self.subTest(case=case):
                if case == "missing_step":
                    self.assertEqual(vc.planned_generation_targets(_env.PROJECT, changed, invalid, job_dir=self.job.job_dir), set())
                    with self.assertRaisesRegex(ValueError, "missing its scene brief"):
                        run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, changed, invalid)
                else:
                    with self.assertRaises(ValueError):
                        vc.planned_generation_targets(_env.PROJECT, changed, invalid, job_dir=self.job.job_dir)
        unconfigured = copy.deepcopy(config)
        unconfigured["generation_enabled"] = False
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", unconfigured)
        with self.assertRaisesRegex(ValueError, "selected channel"):
            vc.planned_generation_targets(_env.PROJECT, director, treatment, job_dir=self.job.job_dir)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        damaged = copy.deepcopy(director)
        damaged["segments"][0]["bindings"]["component-1"]["brief_sha256"] = "b" * 64
        damaged_treatment = copy.deepcopy(treatment)
        path = self.job.job_dir / "damaged-native.json"
        path.write_text("{}")
        damaged_treatment["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": path.name}]
        self.assertEqual(vc.planned_generation_targets(_env.PROJECT, damaged, damaged_treatment, job_dir=self.job.job_dir), set())
        with self.assertRaisesRegex(ValueError, "brief differs"):
            run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, damaged, damaged_treatment)
        unrelated = copy.deepcopy(director)
        neighbor = copy.deepcopy(segment)
        neighbor["segment_id"] = "seg-002"
        unrelated["segments"].append(neighbor)
        with self.assertRaisesRegex(ValueError, "missing its scene brief"):
            run_stage._validate_prepared_native_inputs(self.job, _env.PROJECT, unrelated, treatment,
                planned={("seg-001", "component-1")})
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                return_value=[{"text": "实际剪后口播", "start": 0.0, "end": 3.0}]), \
             mock.patch.object(run_stage, "prepare_visual_dependencies"):
            result = run_stage.run_visual_direction(self.job.job_dir, _env.PROJECT,
                self.fixture.brief, self.treatment)
        self.job = state.load_job(self.job.job_dir)
        self.assertIn("confirmation_source", result)
        self.assertFalse((self.job.job_dir / "generated-media").exists())
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)
        self.confirm()
        from edit.hd.tools import generation_channels, generation_queue
        from PIL import Image
        import paper_hyperframes_adapter as paper
        image = self.job.job_dir / "actual-paper.png"
        Image.new("RGB", (128, 128), "blue").save(image)
        with mock.patch.object(generation_queue, "_approved", return_value=(self.job.job_id, "fixture-config", config)):
            action = vc.generation_actions(self.job)[0]
            generation_channels.record_result(self.job.job_dir, action, {"status": "completed", "artifacts": [{"type": "image", "path": str(image)}]})
            pending = run_stage.resume_visual_direction(self.job, _env.PROJECT)
        self.assertEqual(pending["actions"][0]["action"], "prepare_template_inputs")
        output = pending["actions"][0]["completed_generations"][0]["completion_response"]["artifacts"][0]
        local = Path(output["path"])
        local = local if local.is_absolute() else self.job.job_dir / local
        action = paper.authoring_context(_env.PROJECT, output_directory=self.job.job_dir / "paper-authoring",
            source_binding={"aroll_sha256": artifacts.sha256_file(self.job.job_dir / "06-edit-structure/edited-aroll.mp4"),
                "segment_id": "seg-001", "start": 0.0, "end": 3.0},
            composition={"width":1080,"height":1920,"fps":24,"frames":72,"alpha":False},
            template_request={"semantic_family":"explanation","information_units":1,"numeric_values":[],"numeric_scale":"not_applicable"},
            transcript="实际剪后口播", semantic_goal="资料解释", assets=[local], speech=None, word_anchors=[],
            authorization={"paid_generation":False}, parent_subtitle_layout=None)
        self.assertEqual(action["requirements"]["assets"], [{"path": str(local.resolve()), "sha256": artifacts.sha256_file(local)}])
        with self.assertRaisesRegex(ValueError, "missing its scene brief"):
            run_stage.resume_visual_direction(self.job, _env.PROJECT, {"realization": {
                "director_brief": str(self.fixture.brief), "treatment": str(self.treatment),
                "host_qa_note": "Image exists; native scene is deliberately not prepared"}})

    def test_generated_image_consumption_belongs_to_its_native_component(self):
        from PIL import Image
        root = self.job.job_dir
        image = root / "actual-generated.png"
        Image.new("RGB", (64, 64), "blue").save(image)
        digest = artifacts.sha256_file(image)
        brief = root / "native-inputs/actual-native-brief.json"
        artifacts.write_json_artifact(brief, {"assets": [{"job_path": image.name, "sha256": digest}]})
        director = {"segments": [{"segment_id": "seg-001", "bindings": {"component-1": {}}},
                                 {"segment_id": "seg-002", "bindings": {"component-1": {}}}]}
        native = {"segment_id": "seg-002", "component_id": "component-1", "artifact": vc._record(root, brief)}
        hashes = vc._realized_media_hashes(root, director, [], [native])
        self.assertNotIn(digest, hashes[("seg-001", "component-1")])
        self.assertIn(digest, hashes[("seg-002", "component-1")])
        native["segment_id"] = "seg-001"
        self.assertIn(digest, vc._realized_media_hashes(root, director, [], [native])[("seg-001", "component-1")])
        brief.write_text("{}")
        with self.assertRaisesRegex(vc.VisualConfirmationError, "evidence changed"):
            vc._realized_media_hashes(root, director, [], [native])

    def _selected_generation_flow(self, reference_mode):
        from edit.hd.tools import generation_channels as channel, generation_queue as queue, startup
        import generated_media
        config = {"schema_version": 1, "generation_enabled": True, "max_concurrency": 2,
                  "providers": [{"purpose": purpose, "provider": "fixture", "model": purpose + "-model",
                    "endpoint_id": "fixture." + purpose, "connection_status": "verified",
                    "quota_status": "available", "reference_images": True, "native_9_16": True,
                    "silent_output": True} for purpose in ("image", "video")]}
        artifacts.write_json_artifact(self.job.job_dir / "manifests/provider-config.json", config)
        artifacts.write_json_artifact(self.job.job_dir / "manifests/generation-channels.json",
            {"schema_version": 1,
             "image": {"model_binding": {"mode": "fixed"}, "reference_mode": "local_path"},
             "video": {"model_binding": {"mode": "argument", "parameter": "model"},
                       "reference_mode": reference_mode,
                       "upload": {"tool": "fixture.upload", "arguments": {"file": {"$input": "path"}},
                                  "result_path": ["data", "asset_id"]},
                       "query": {"tool": "fixture.query", "arguments": {}, "task_ids_parameter": "task_ids"}}})
        segment = fixture_api.draft_segment(("ai_generated",))
        segment["bindings"]["component-1"] = {"provider": "fixture", "model": "video-model", "endpoint_id": "fixture.video"}
        segment = avatar_profile.plan_avatar_policy([segment])["segments"][0]
        self.fixture._write_brief(segment)
        arguments_path = self.job.job_dir / "channel-arguments.json"
        artifacts.write_json_artifact(arguments_path, {"prompt": "fixture request"})
        cli = subprocess.run([sys.executable, str(_env.SKILL / "scripts/run_generation.py"),
            "--project-root", str(_env.PROJECT), "--job", str(self.job.job_dir), "prepare",
            "--purpose", "image", "--request-id", "fixture-cli", "--arguments-json", str(arguments_path)],
            cwd="/tmp", check=True, capture_output=True, text=True)
        import json
        self.assertEqual(json.loads(cli.stdout)["tool"], "fixture.image")
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = [{"segment_id": "seg-001", "component_id": "component-1", "tags": ["蓝色场景"]}]
        treatment["skill_selection"]["fixed_context"][0]["skill_id"] = "fixture"
        treatment["generation_plan"] = {"steps": [
            {"id": "image", "purpose": "image", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "a blue scene"}, "depends_on": []},
            {"id": "video", "purpose": "video", "segment_id": "seg-001", "component_id": "component-1",
             "arguments": {"prompt": "animate blue scene", "reference": {"$step": "image", "output": 0}}, "depends_on": ["image"]}]}
        artifacts.write_json_artifact(self.treatment, treatment)
        treatment = self._review_creator(segment, treatment,
            "muyang-flat-animation:muyang-flat-animation/design")
        artifacts.write_json_artifact(self.treatment, treatment)
        if reference_mode == "upload":
            missing_snapshot = copy.deepcopy(treatment)
            missing_snapshot["skill_selection"]["overlay_beats"] = [
                {"segment_id": "seg-001", "component_id": "component-1"}]
            artifacts.write_json_artifact(self.treatment, missing_snapshot)
            with self.assertRaisesRegex(vc.VisualConfirmationError, "binding snapshot is missing or stale"):
                self.prepare()
            artifacts.write_json_artifact(self.treatment, treatment)
            planned = artifacts.read_json_artifact(self.fixture.brief)
            planned["segments"][0]["bindings"]["component-1"]["generation_id"] = "video"
            artifacts.write_json_artifact(self.fixture.brief, planned)
            invalid_identity = copy.deepcopy(treatment)
            invalid_identity["skill_selection"]["beats"][0]["binding_snapshot"] = copy.deepcopy(
                planned["segments"][0]["bindings"]["component-1"])
            artifacts.write_json_artifact(self.treatment, invalid_identity)
            with self.assertRaisesRegex(vc.VisualConfirmationError, "omit completed generation identity"):
                self.prepare()
            self.assertFalse(list((self.job.job_dir / vc.DIRECTORY).glob("*/proposal.json")))
            del planned["segments"][0]["bindings"]["component-1"]["generation_id"]
            artifacts.write_json_artifact(self.fixture.brief, planned)
            artifacts.write_json_artifact(self.treatment, treatment)
        with mock.patch("edit.hd.tools.motion_capabilities._approved_speech",
                return_value=[{"text": "实际剪后口播", "start": 0.0, "end": 3.0}]):
            run_stage.run_visual_direction(self.job.job_dir, _env.PROJECT, self.fixture.brief, self.treatment)
        self.job = state.load_job(self.job.job_dir)
        self.confirm()
        image = self.job.job_dir / "source-image.png"
        from PIL import Image
        Image.new("RGB", (1080, 1920), "blue").save(image)
        video = self.job.job_dir / "source-video.mp4"
        original_video = self.job.job_dir / "provider-original-30fps.mp4"
        source = original_video if reference_mode == "upload" else video
        rate = 30 if reference_mode == "upload" else 24
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=blue:s=1080x1920:r={rate}:d=3",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        if reference_mode == "upload":
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(original_video), "-r", "24", "-an",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        original_confirmation = vc.validate_visual_authorization(self.job)["artifact"]
        # Only the independent, already-tested startup gate is a fixture. Queue,
        # authorization, actions, result copying, compiler and adapters are real.
        with mock.patch.object(queue, "_approved", return_value=(self.job.job_id, "fixture-config", config)):
            actions = vc.generation_actions(self.job)
            self.assertNotIn("model", actions[0]["arguments"])
            self.assertEqual([a["tool"] for a in actions], ["fixture.image"])
            channel.record_result(self.job.job_dir, actions[0], {"status": "completed", "artifacts": [{"type": "image", "path": str(image)}]})
            actions = vc.generation_actions(self.job)
            if reference_mode == "upload":
                upload = actions[0]
                self.assertEqual(upload["tool"], "fixture.upload")
                self.assertTrue(Path(upload["arguments"]["file"]).is_file())
                # A technical proposal revision must reuse the already-authorized
                # request and pending upload without rewriting the old receipt.
                before = queue.status(self.job.job_dir)
                old_auth = copy.deepcopy(before["items"][upload["request_id"]]["authorization"])
                previous_source = vc.validate_visual_authorization(self.job)["source"]["source_id"]
                state.revise(self.job, "visual_direction", "same content, technical preparation revised")
                revised = artifacts.read_json_artifact(self.treatment)
                revised["planning_notes"] = ["technical preparation checked; same generation content"]
                revised["numbering_scope_id"] = "scope-renumbered-plan"
                treatment["numbering_scope_id"] = revised["numbering_scope_id"]
                artifacts.write_json_artifact(self.treatment, revised)
                self.prepare(); self.confirm()
                current = vc.validate_visual_authorization(self.job)
                self.assertNotEqual(current["source"]["source_id"], previous_source)
                self.assertEqual(current["source"]["numbering_scope_id"], "scope-renumbered-plan")
                original_confirmation = current["artifact"]
                resumed_actions = vc.generation_actions(self.job)
                self.assertEqual(resumed_actions[0]["status"], "input_upload_pending")
                self.assertEqual(resumed_actions[0]["request_id"], upload["request_id"])
                after = queue.status(self.job.job_dir)
                self.assertEqual(set(after["items"]), set(before["items"]))
                self.assertEqual(after["items"][upload["request_id"]]["authorization"], old_auth)
                step = current["source"]["generation_steps"][1]
                request = vc.resolve_generation_request(self.job, current["source"], step)
                self.assertEqual(request["id"], upload["request_id"])
                changed = copy.deepcopy(request)
                changed["arguments"]["prompt"] = "different request"
                self.assertIsNone(vc._equivalent_request_id(after, changed, step["id"], self.job))
                # Exercise the same stage entry the host uses for upload results.
                resumed = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"generation_results": [
                    {"action": upload, "response": {"data": {"asset_id": "actual-fixture-upload-id"}}}]})
                actions = resumed["actions"]
            self.assertEqual(actions[0]["tool"], "fixture.video")
            self.assertEqual(actions[0]["arguments"]["model"], "video-model")
            if reference_mode == "upload":
                self.assertEqual(actions[0]["arguments"]["reference"], "actual-fixture-upload-id")
            else:
                self.assertTrue(Path(actions[0]["arguments"]["reference"]).is_file())
            channel.record_result(self.job, actions[0], {"status": "pending", "task_ids": ["task-real-fixture"], "poll_after_seconds": 10})
            with mock.patch.object(channel.time, "time", return_value=time.time() + 60):
                query = vc.generation_actions(self.job)[0]
            self.assertEqual(query["tool"], "fixture.query")
            output = {"type": "video", "path": str(video)}
            if reference_mode == "upload":
                output.update(source={"path": str(original_video)}, processing="convert 30fps to 24fps; retain original")
                with self.assertRaisesRegex(ValueError, "both original source"):
                    channel.record_result(self.job, query, {"status": "completed", "artifacts": [
                        {key: value for key, value in output.items() if key != "source"}]})
            channel.record_result(self.job.job_dir, query, {"status": "completed", "artifacts": [output]})
            self.assertEqual(vc.generation_actions(self.job), [])
            proposal = vc.validate_visual_authorization(self.job)["source"]
            rid, _ = vc.generation_item(queue.status(self.job.job_dir), proposal, proposal["generation_steps"][1])
            aroll = next(r for r in self.job.stages["edit_structure"]["artifacts"] if r["path"].endswith("edited-aroll.mp4"))
            record = generated_media.record_from_queue(self.job, rid, segment_id="seg-001", component_id="component-1",
                source_binding={"aroll_sha256": aroll["sha256"], "start": 0.0, "end": 3.0},
                qa={"passed": True, "observed_scene": "Actual solid blue scene"},
                semantic_brief={"observed_scene": "Actual solid blue scene"}, ffprobe_executable="ffprobe")
            self.assertEqual(record["model"], "video-model")
            if reference_mode == "upload":
                self.assertTrue(Path(record["generation"]["source_media"]["path"]).is_file())
                self.assertEqual(record["generation"]["source_media"]["sha256"], artifacts.sha256_file(original_video))
                self.assertTrue(record["generation"]["input_bindings"])
                self.assertEqual(record["generation"]["submitted_request"]["arguments"]["reference"], "actual-fixture-upload-id")
                self.assertEqual(vc.validate_visual_authorization(self.job)["artifact"], original_confirmation)
            record_path = self.job.job_dir / "native-inputs/completed.json"
            artifacts.write_json_artifact(record_path, record)
            with self.assertRaisesRegex(ValueError, "another approved visual row"):
                generated_media.record_from_queue(self.job, rid, segment_id="wrong-row", component_id="component-1",
                    source_binding={}, qa={}, semantic_brief={}, ffprobe_executable="ffprobe")
            segment["bindings"]["component-1"] = generated_media.prepare_binding(record)
            treatment["skill_selection"]["beats"][0]["binding_snapshot"] = copy.deepcopy(segment["bindings"]["component-1"])
            realized_director = self.job.job_dir / "native-inputs/realized-director.json"
            artifacts.write_json_artifact(realized_director, {"schema_version": 3, "segments": [segment]})
            ref = vc._record(self.job.job_dir, record_path)
            treatment["scenes"] = [{"segment_id": "seg-001", "component_id": "component-1", "brief_path": ref["path"],
                 "completed_record": {"job_path": ref["path"], "sha256": ref["sha256"], "byte_count": ref["bytes"]}}]
            realized_treatment = self.job.job_dir / "native-inputs/realized-treatment.json"
            artifacts.write_json_artifact(realized_treatment, treatment)
            from edit.hd.tools import motion_capabilities
            motion_capabilities._ai_brief_evidence(self.job.job_dir, treatment, segment, "component-1")
            result = run_stage.resume_visual_direction(self.job, _env.PROJECT, {"realization": {
                "director_brief": str(realized_director), "treatment": str(realized_treatment), "host_qa_note": "Actual blue media checked"}})
            self.assertEqual(result["status"], "approved")
            adapters = run_stage.native_component_adapters(_env.PROJECT, state.load_job(self.job.job_dir))
            self.assertIn(("seg-001", "component-1"), adapters["ai_generated"])
            self.assertTrue(image.is_file() and video.is_file())

    def test_startup_allows_one_selected_generation_channel(self):
        from edit.hd.tools import startup
        image = {"purpose": "image", "provider": "fixture", "model": "image-model", "endpoint_id": "fixture.image",
                 "connection_status": "verified", "quota_status": "available"}
        config = {"generation_enabled": True, "providers": [image]}
        self.assertEqual(startup.selected_channels(config)["image"]["endpoint_id"], "fixture.image")
        video = {**image, "purpose": "video", "model": "video-model", "endpoint_id": "fixture.video"}
        config["providers"].append(video)
        self.assertEqual(startup.selected_channels(config)["video"]["endpoint_id"], "fixture.video")

    def test_unconfirmed_proposal_cannot_start_generation(self):
        self.prepare()
        with self.assertRaisesRegex(vc.VisualConfirmationError, "not been confirmed"):
            vc.generation_actions(self.job)

    def test_confirmation_requires_explicit_motion_query_tags(self):
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["motion_queries"] = []
        director = artifacts.read_json_artifact(self.fixture.brief)
        with self.assertRaisesRegex(vc.VisualConfirmationError, "explicit semantic retrieval tags"):
            vc._rows(director, treatment, [])

    def test_direct_material_keeps_source_separate_from_template(self):
        director = artifacts.read_json_artifact(self.fixture.brief)
        treatment = artifacts.read_json_artifact(self.treatment)
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["tags"], ["approved visual explanation"])
        self.assertEqual(rows[0]["source"], "asset-1")
        self.assertEqual(rows[0]["template"], "素材直用（无动效模板）")
        self.assertEqual(rows[0]["channel"], "Example Stock")

    def test_native_creation_uses_the_registered_template_in_the_list(self):
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        director = artifacts.read_json_artifact(self.fixture.brief)
        segment = director["segments"][0]
        segment["visual_strategy"]["components"][0]["kind"] = "code_generated"
        segment["bindings"]["component-1"] = {"dependency_id": "openfilm-motion-graphics",
                                               "template_id": "openfilm/motion-graphics-scene"}
        treatment = artifacts.read_json_artifact(self.treatment)
        treatment["skill_selection"]["assignments"] = [{"segment_id": "seg-001", "component_id": "component-1",
            "candidate_id": "openfilm-motion-graphics:motion-graphics", "skill_id": "openfilm-motion-graphics",
            "template_id": "openfilm/motion-graphics-scene", "role": "native"}]
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["template"], "openfilm/motion-graphics-scene")
        self.assertEqual(rows[0]["channel"], "openfilm-motion-graphics")
        segment["visual_strategy"]["components"][0]["kind"] = "ai_generated"
        segment["bindings"]["component-1"] = {"provider": "Lovart", "generation_id": "fixture-generation"}
        treatment["skill_selection"]["assignments"][0].update(candidate_id="gbro-collage-broll:design",
            skill_id="gbro-collage-broll", template_id="gbro-collage-broll/design", role="design")
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual(rows[0]["channel"], "gbro-collage-broll")
        self.assertEqual(rows[0]["template"], "gbro-collage-broll/design")
        self.assertEqual(rows[0]["generation_channel"], "Lovart")
        treatment["generation_plan"] = {"steps": [{"id":"image", "purpose":"image",
            "segment_id":segment["segment_id"], "component_id":"component-1", "arguments":{}},
            {"id":"video", "purpose":"video", "segment_id":segment["segment_id"],
             "component_id":"component-1", "arguments":{}, "depends_on":["image"]}]}
        rows = vc._rows(director, treatment, [],
            validate_semantic_lists(treatment, director)["component_rows"], {
                "image":{"provider":"Builtin", "model":"image-model"},
                "video":{"provider":"Lovart", "model":"Kling O1"}})
        self.assertEqual(rows[0]["channel"], "gbro-collage-broll")
        self.assertEqual(rows[0]["generation_channel"], "图片：Builtin / image-model；视频：Lovart / Kling O1")
        self.assertEqual(rows[0]["template"], "gbro-collage-broll/design")

    def test_channel_uses_real_source_instead_of_adapter_alias(self):
        director = {"segments": []}
        treatment = {"motion_queries": []}
        for index, dependency in enumerate(("hyperframes", "hyperframes-native-adaptation")):
            sid = f"seg-{index}"
            director["segments"].append({"segment_id": sid, "start": index, "end": index + 1,
                "visual_intent": {"statement": "顺序展开"},
                "visual_strategy": {"components": [{"component_id": "scene", "kind": "code_generated",
                                                     "layer_role": "base"}]},
                "bindings": {"scene": {"dependency_id": dependency, "template_id": f"template-{index}"}}})
            treatment["motion_queries"].append({"segment_id": sid, "component_id": "scene", "tags": ["顺序展开"]})
        from edit.hd.tools.semantic_visual_plan import validate_semantic_lists
        treatment["semantic_lists"] = {"overlay": [], "broll": [{
            "row_id": "shared", "start_word": 0, "end_word": 1, "quote": "x", "semantic": "顺序展开",
            "visual_task": "顺序展开", "components": [{"segment_id": f"seg-{i}", "component_id": "scene"}
                                                       for i in range(2)]}]}
        rows = vc._rows(director, treatment, [], validate_semantic_lists(treatment, director)["component_rows"])
        self.assertEqual([r["channel"] for r in rows], ["hyperframes", "hyperframes"])
        self.assertEqual([r["template"] for r in rows], ["template-0", "template-1"])

class NativeSupplementBoundaryTests(unittest.TestCase):
    def setUp(self):
        import tempfile, json, hashlib
        from test_motion_native_skill_adapter import brief
        import motion_native_skill_adapter as native
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.native=native
        base=fixture_api.draft_segment(('ai_generated',),end=2)
        base['visual_strategy']['components'][0].update(media_type='video',layout_slot='full_frame')
        sid=base['segment_id'];cid=base['visual_strategy']['components'][0]['component_id'];aid='advice'
        self.sid,self.cid,self.aid=sid,cid,aid
        request=brief();self.request=request
        source_task={'semantic_row_id':'task','quote':request['transcript'],'semantic':request['semantic_goal'],
                     'required_change':request['task_source']['required_change'],
                     'component_brief':base['visual_strategy']['components'][0]['brief']}
        request['task_source']=source_task
        base['bindings']={cid:{'provider':'Lovart','model':'approved-model','endpoint_id':'approved-video'}}
        self.old={'schema_version':3,'segments':[base]}
        row={'row_id':'task','quote':request['transcript'],'semantic':request['semantic_goal'],
             'components':[{'segment_id':sid,'component_id':cid}]}
        beat={'segment_id':sid,'component_id':cid,'semantic_row_id':'task','transcript':request['transcript'],
              'required_change':source_task['required_change'],'component_brief':source_task['component_brief']}
        self.old_t={'semantic_lists':{'broll':[row],'overlay':[]},'scenes':[],
                    'skill_selection':{'beats':[beat],'assignments':[]},'motion_readability':[],
                    'motion_queries':[],'beat_sheet':[{'components':[{'segment_id':sid,'component_id':cid}]}]}
        self.director=copy.deepcopy(self.old);self.treatment=copy.deepcopy(self.old_t)
        new=self.director['segments'][0];strategy=new['visual_strategy'];strategy['mode']='hybrid'
        action={**strategy['components'][0],'component_id':aid,'kind':'code_generated',
                'layer_role':'annotation','layout_slot':'annotation','media_type':'animation'}
        strategy['components'].append(action)
        strategy['composition'].update(family='evidence_with_data_overlay',reading_order=[cid,aid],
            component_dependencies=[{'component_id':aid,'depends_on':[cid]}])
        media=self.root/'base.mp4';media.write_bytes(b'actual registered provider bytes')
        ref=native.descriptor(self.root,media)
        self.record={'job_id':request['job_id'],'status':'completed','segment_id':sid,'component_id':cid,
            'source_binding':{k:request['source_binding'][k] for k in ('aroll_sha256','start','end')},
            'media':{**ref,'media_type':'video'},'source_dimensions':{'width':1080,'height':1920},
            'composition_base':{'action_component_id':aid,'source_qa':{'passed':False,'observed_scene':'Missing advice'}},
            'qa':{'passed':True,'scope':'composition_base','observed_scene':'Usable task base only'},
            'generation':{'approved_request_id':'request','approved_request':{'id':'request'},
                          'approved_plan':{'source':{'fixture':'existing receipt'},'steps':{'request':'video-step'}}}}
        request['materials']=[ref]
        request['alpha']=True
        self.path=self.root/'native-inputs/alpha-brief.json';self.path.parent.mkdir()
        artifacts.write_json_artifact(self.path,request)
        new['bindings'][aid]={'dependency_id':'barty-motion-graphics',
            'brief_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}
        new['bindings'][cid].update(execution_mode='reuse_completed_generated_media',sha256=ref['sha256'])
        record_path=self.root/'base-record.json';artifacts.write_json_artifact(record_path,self.record)
        self.treatment['scenes']=[{'segment_id':sid,'component_id':cid,'completed_record':native.descriptor(self.root,record_path)},
            {'segment_id':sid,'component_id':aid,'brief_path':'native-inputs/alpha-brief.json'}]
        self.treatment['semantic_lists']['broll'][0]['components'].append({'segment_id':sid,'component_id':aid})
        self.treatment['beat_sheet'][0]['components'].append({'segment_id':sid,'component_id':aid})
        self.treatment['beat_sheet'][0]['merge_reason']='Native advice belongs to the same original task'
        self.treatment['skill_selection']['beats'].append({**beat,'component_id':aid})
        self.treatment['motion_readability']=[{'segment_id':sid,'component_id':aid,'targets':[],'pending_native':True}]
        self.treatment['native_supplements']=[{'segment_id':sid,'base_component_id':cid,'action_component_id':aid,
                                            'reason':'Actual source misses the approved advice action'}]
        d=self.root/'original-director.json';t=self.root/'original-treatment.json'
        artifacts.write_json_artifact(d,self.old);artifacts.write_json_artifact(t,self.old_t)
        self.proposal={'inputs':{'director':vc._record(self.root,d),'treatment':vc._record(self.root,t)},
                      'generation_steps':[{'id':'video-step','segment_id':sid,'component_id':cid,'purpose':'video'}]}

    def validate(self,director=None,treatment=None):
        from edit.hd.tools import motion_capabilities
        with mock.patch.object(vc,'_native_result_adapter',return_value=self.native), \
             mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(self.record,{})), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)):
            vc._validate_draft_against_source(self.root,self.proposal,director or self.director,treatment or self.treatment)

    def test_pending_supplement_retains_original_plan_and_rejects_source_task_or_clock_drift(self):
        from edit.hd.tools import visual_strategy
        segment=self.director['segments'][0]
        visual_strategy.validate_visual_strategy(segment['visual_intent'],segment['visual_strategy'])
        self.validate()
        for field in ('time','meaning','avatar','base','paid','queue','unrelated'):
            d,t=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
            if field=='time':d['segments'][0]['end']=3
            if field=='meaning':t['semantic_lists']['broll'][0]['semantic']='another meaning'
            if field=='avatar':d['segments'][0]['visual_strategy']['composition']['presenter_mode']='hidden'
            if field=='base':d['segments'][0]['visual_strategy']['components'][0]['brief']='another task'
            if field=='paid':t['generation_plan']={'steps':[{'new':'paid request'}]}
            if field=='queue':
                self.record['generation']['approved_plan']['steps']['request']='wrong-step'
            if field=='unrelated':d['segments'].append(copy.deepcopy(d['segments'][0]))
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(d,t)
            self.record['generation']['approved_plan']['steps']['request']='video-step'
        self.assertEqual(self.old['segments'][0]['visual_strategy']['mode'],'single')
        self.assertEqual(self.director['segments'][0]['visual_strategy']['mode'],'hybrid')
        self.assertEqual(self.old['segments'][0]['strategy_revision'],self.director['segments'][0]['strategy_revision'])
        changed=copy.deepcopy(self.director);changed['segments'][0]['strategy_revision']+=1
        with self.assertRaisesRegex(ValueError,'technical strategy revision needs'):
            self.validate(director=changed)

    def test_completed_supplement_requires_real_native_result_alignment_and_text(self):
        result=self.root.joinpath(self.request['result_record_path']);result.parent.mkdir(parents=True,exist_ok=True)
        result.write_text('{}')
        with self.assertRaisesRegex(ValueError,'alignment'):
            self.validate()
        self.root.joinpath(self.request['result_record_path']).unlink()
        changed=copy.deepcopy(self.treatment)
        changed['motion_readability'][0].pop('pending_native')
        with self.assertRaisesRegex(ValueError,'unfinished'):
            self.validate(treatment=changed)

    def test_completed_supplement_reuses_hybrid_checks_and_exact_rendered_text(self):
        source=self.root/'source.html';source.write_text('<p>建议</p>')
        call=self.root/'call.json';artifacts.write_json_artifact(call,{'project_files':[self.native.descriptor(self.root,source)]})
        alpha=self.root/'alpha.mov';alpha.write_bytes(b'isolated native output fixture')
        result={'status':'completed','media':self.native.descriptor(self.root,alpha),
                'render_call':self.native.descriptor(self.root,call)}
        result_path=self.root/self.request['result_record_path'];result_path.parent.mkdir(parents=True)
        artifacts.write_json_artifact(result_path,result)
        binding=self.director['segments'][0]['bindings'][self.aid]
        binding['invocation_record']={'canvas_alignment':{'mode':'identity','base_component_id':self.cid,
            'base_sha256':self.record['media']['sha256'],'layer_sha256':result['media']['sha256']}}
        self.director['segments'][0]['visible_text']=['建议']
        target={'target_id':'advice','content_ref':{'path':'source.html','sha256':self.native.sha(source),
                'pointer':'text:3:5','value':'建议'},'span':[0,2],'role':'title',
                'region':{'x':100,'y':200,'width':400,'height':100},'windows':[{'start':.5,'end':1.5}]}
        self.treatment['motion_readability'][0]={'segment_id':self.sid,'component_id':self.aid,'targets':[target]}
        self.treatment['semantic_assessments']=[{'segment_id':self.sid,'component_id':self.aid,
            'candidate_id':'barty-motion-graphics:barty-motion-graphics/motion-broll','verdict':'pass',
            'content_refs':[{'path':self.request['result_record_path'],'sha256':self.native.sha(result_path),
                             'pointer':'/status','value':'completed'}]}]
        with mock.patch.object(self.native,'inspect_result',return_value=result):
            self.validate()
            changed=copy.deepcopy(self.director)
            changed['segments'][0]['bindings'][self.aid]['invocation_record']['canvas_alignment']['layer_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'action media differs'):self.validate(director=changed)
            changed=copy.deepcopy(self.treatment)
            changed['motion_readability'][0]['targets'][0]['content_ref']['sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'actual rendered native source'):self.validate(treatment=changed)

    def test_camera_realization_requires_the_same_original_proposal_and_queue_pixels(self):
        import generated_media
        from edit.hd.tools import parent_camera_framing as camera, motion_capabilities
        from types import SimpleNamespace
        record=copy.deepcopy(self.record);record.pop('composition_base')
        record['qa']['scope']='framing_source';record['generation']['request_id']='request'
        data={'schema_version':1,'segment_id':self.sid,'component_id':self.cid,
              'source_binding':record['source_binding'],'source_media':record['media'],
              'normalized_media':record['media'],'source_frames':[0,48],
              'path':[{'frame':n,'x':0,'y':0,'width':1080,'height':1920} for n in range(48)],
              'reason':'Focus the original checked calendar without replacing its content'}
        path=self.root/'camera.json';artifacts.write_json_artifact(path,data)
        ref=self.native.descriptor(self.root,path)
        record['camera_source']={'source_qa':{'passed':False,'observed_scene':'Original focus is wrong'},'framing':ref}
        director=copy.deepcopy(self.old);treatment=copy.deepcopy(self.old_t)
        director['segments'][0]['bindings'][self.cid].update(execution_mode='reuse_completed_generated_media',
            sha256=record['media']['sha256'],**{camera.FIELD:ref})
        job=SimpleNamespace(job_dir=self.root,job_id=record['job_id'])
        with mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(record,{})), \
             mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(generated_media,'_queue_media',return_value=record['media']), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)):
            vc._validate_draft_against_source(self.root,self.proposal,director,treatment)
            with mock.patch.object(vc,'_validate_source',return_value=({},{'another':'proposal'})):
                with self.assertRaisesRegex(ValueError,'another approved visual proposal'):
                    vc._validate_draft_against_source(self.root,self.proposal,director,treatment)
            with mock.patch.object(generated_media,'_queue_media',return_value={**record['media'],'sha256':'e'*64}):
                with self.assertRaisesRegex(ValueError,'original generation'):
                    vc._validate_draft_against_source(self.root,self.proposal,director,treatment)

    def test_selector_supplement_scope_reuses_actual_realization_proof_and_source_locks(self):
        from edit.hd.tools import broll_skill_selection as selection, motion_capabilities
        from types import SimpleNamespace
        job=SimpleNamespace(job_dir=self.root,job_id=self.request['job_id'])
        with mock.patch.object(state,'load_job',return_value=job), \
             mock.patch.object(vc,'validate_visual_authorization',return_value={'source':self.proposal}), \
             mock.patch.object(vc,'_validate_source',return_value=({},self.proposal)), \
             mock.patch.object(vc,'_native_result_adapter',return_value=self.native), \
             mock.patch.object(motion_capabilities,'_ai_brief_evidence',return_value=(self.record,{})):
            keys,locks=selection._verified_supplement_routes(self.root,self.director,self.treatment)
            self.assertEqual(keys,{(self.sid,self.aid)})
            self.assertEqual(locks[(self.sid,self.aid)],'barty-motion-graphics:barty-motion-graphics/motion-broll')
            altered=copy.deepcopy(self.director)
            altered['segments'][0]['bindings'][self.cid]['provider']='another source'
            with self.assertRaisesRegex(ValueError,'approved source'):
                selection._verified_supplement_routes(self.root,altered,self.treatment)
            self.record['composition_base']['source_qa']['passed']=True
            with self.assertRaisesRegex(ValueError,'failed-effect scope'):
                selection._verified_supplement_routes(self.root,self.director,self.treatment)


class MotionRealizationBoundaryTests(unittest.TestCase):
    """A native result may reveal text, without changing its approved task."""
    def test_native_repair_binds_registered_prior_mapping_and_next_real_revision(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = {'segments': [{'segment_id': 'seg-001', 'strategy_revision': 1, 'bindings': {
                'native': {'dependency_id': 'bang-motion', 'brief_sha256': 'a' * 64}}}]}
            def write(name, value):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                artifacts.write_json_artifact(path, value)
                return vc._record(root, path)
            director = write('director.json', old)
            treatment = write('treatment.json', {'scenes': [
                {'segment_id': 'seg-001', 'component_id': 'native'}]})
            config = write('manifests/provider-config.json', {})
            write('workflow.json', {'job_id': 'job'})
            proposal = write('proposal.json', {'job_id': 'job', 'kind': vc.SCHEMA,
                'provider_config_sha256': config['sha256'], 'inputs': {'director': director}})
            approval = write('receipt.json', {'source_schema': vc.SCHEMA, 'job_id': 'job',
                'job_dir': str(root), 'stage': 'visual_direction', 'passed': True,
                'reviewed_by': 'human', 'approval_scope': 'visual_plan_and_delivery',
                'note': 'fixture', 'user_confirmation': 'approved', 'artifacts': [], 'source': proposal})
            previous = write('prior/execution-mapping.json', {'proposal': proposal, 'source_approval': approval,
                'realization_inputs': {'director': director, 'treatment': treatment}})
            scene = {'native_revision_from': previous, 'native_revision_reason': '实际光标遮字，修原生自有输入'}
            current = copy.deepcopy(old['segments'][0]); current['strategy_revision'] = 2
            current['bindings']['native']['brief_sha256'] = 'b' * 64
            job = SimpleNamespace(stages={'visual_direction': {'artifacts': [previous], 'lineage': []}})
            with mock.patch.object(state, 'load_job', return_value=job):
                vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), current, scene)
                vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), old['segments'][0], scene)
                for mutation in ('skip_revision', 'same_input', 'meaning', 'unregistered'):
                    changed = copy.deepcopy(current)
                    if mutation == 'skip_revision': changed['strategy_revision'] = 3
                    elif mutation == 'same_input': changed['bindings']['native']['brief_sha256'] = 'a' * 64
                    elif mutation == 'meaning': changed['visual_intent'] = {'statement': '另一件事'}
                    else: job.stages['visual_direction']['artifacts'] = []
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        vc._verify_native_revision_origin(root, old, ('seg-001', 'native'), changed, scene)

    def test_technical_revision_requires_scoped_verified_implementation_change(self):
        base = {'segments': [{'segment_id': 'seg-1', 'strategy_revision': 1, 'bindings': {
            'action': {'dependency_id': 'barty-motion-graphics', 'invocation_record': {}}}}]}
        actual = copy.deepcopy(base); actual['segments'][0]['strategy_revision'] = 2
        with self.assertRaisesRegex(ValueError, 'verified implementation'):
            vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)
        actual['segments'][0]['bindings']['action']['invocation_record']['canvas_alignment'] = {'mode': 'identity'}
        normalized = vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)
        self.assertEqual(normalized['segments'][0]['strategy_revision'], 1)
        self.assertEqual(actual['segments'][0]['strategy_revision'], 2)
        actual['segments'][0]['strategy_revision'] = 0
        with self.assertRaisesRegex(ValueError, 'must increase'):
            vc._normalize_verified_technical_revisions(base, {}, actual, {}, actual)

    def test_lemo_number_size_change_does_not_allow_other_source_edits(self):
        old = "before; paint(String(step),px,py+10,30,color,'center','Font');after"
        new = "before; paint(String(step),px,py+12,36,color,'center','Font');after"
        self.assertEqual(vc._lemo_number_change(old, new), (30, 36))
        for changed in (new.replace('after', 'different'), new.replace('color', 'other'),
                        new.replace('py+12', 'py+90'), new.replace(',36,', ',20,')):
            with self.assertRaises(ValueError):
                vc._lemo_number_change(old, changed)

    def test_lemo_measurement_must_match_decoded_composite_pixels(self):
        from PIL import Image
        frame = self.root / 'frame.png'
        Image.new('RGB', (1080, 1920), 'white').save(frame)
        measured = {'samples': [{'frame': 0, 'time': 0, 'frame_path': 'frame.png',
            'frame_sha256': artifacts.sha256_file(frame), 'digits': [{'measurements': [
                {'bbox': [10, 10, 10, 36], 'height': 36, 'method': 'bright_core'}]}]}]}
        rgb = bytes([255]) * (1080 * 1920 * 3)
        with mock.patch.object(vc.subprocess, 'check_output', return_value=rgb):
            vc._verify_lemo_measured_frames(self.root, self.root / 'video.mp4', measured, 1)
        with mock.patch.object(vc.subprocess, 'check_output', return_value=bytes(len(rgb))):
            with self.assertRaisesRegex(ValueError, 'not from the composite'):
                vc._verify_lemo_measured_frames(self.root, self.root / 'video.mp4', measured, 1)

    def test_transparency_does_not_change_the_actual_component_use(self):
        brief = {'template_id': 'motion-broll', 'alpha': True}
        component = {'component_id': 'scene', 'layer_role': 'annotation'}
        segment = {'visual_strategy': {'composition': {'family': 'broll_with_avatar'}, 'components': [component]}}
        candidate = vc.native_candidate_id('barty-motion-graphics', brief, segment, 'scene')
        self.assertEqual(candidate, 'barty-motion-graphics:barty-motion-graphics/motion-broll')
        segment['visual_strategy']['composition']['family'] = 'aroll_with_overlay'
        self.assertEqual(vc.native_candidate_id('barty-motion-graphics', brief, segment, 'scene'),
                         'overlay:barty-motion-graphics/motion-broll')
        with self.assertRaises(vc.VisualConfirmationError):
            vc.native_candidate_id('barty-motion-graphics', brief, segment, 'wrong')

    def setUp(self):
        import tempfile
        from test_motion_native_skill_adapter import brief
        import motion_native_skill_adapter as native
        self.native = native
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        segment = fixture_api.draft_segment(('code_generated',), end=2)
        cid = 'component-1'
        self.director = {'schema_version': 3, 'segments': [segment]}
        request = brief()
        request['task_source']['component_brief'] = segment['visual_strategy']['components'][0]['brief']
        self.treatment = {'numbering_scope_id': 'native-test', 'scenes': [],
            'semantic_lists': {'overlay': [], 'broll': [{'row_id': 'semantic-1', 'quote': request['transcript'],
                'semantic': request['semantic_goal'], 'visual_task': '可替换的参考构图',
                'components': [{'segment_id': 'seg-001', 'component_id': cid}]}]},
            'skill_selection': {'beats': [{'segment_id': 'seg-001', 'component_id': cid, 'semantic_row_id': 'semantic-1',
                'required_change': request['task_source']['required_change'], 'transcript': request['transcript'],
                'component_brief': segment['visual_strategy']['components'][0]['brief']}], 'overlay_beats': []},
            'semantic_assessments': [{'segment_id': 'seg-001', 'component_id': cid,
                'candidate_id': 'barty-motion-graphics:barty-motion-graphics/motion-broll', 'verdict': 'pass',
                'reason': '批准语义', 'transcript_refs': [], 'content_refs': []}],
            'motion_readability': [{'segment_id': 'seg-001', 'component_id': cid, 'targets': [], 'pending_native': True}]}
        path = self.root / 'native-inputs/approved.json'; artifacts.write_json_artifact(path, request)
        digest = native.sha(path)
        binding = {'dependency_id': 'barty-motion-graphics', 'template_id': 'barty-motion-graphics/motion-broll',
                   'source_sha256': 'a' * 64, 'brief_sha256': digest,
                   'verification_id': __import__('hashlib').sha256(('a' * 64 + digest).encode()).hexdigest()}
        segment['bindings'] = {cid: binding}
        self.treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(binding)
        self.treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': cid, 'brief_path': 'native-inputs/approved.json'}]
        dpath = self.root / 'approved-director.json'; tpath = self.root / 'approved-treatment.json'
        artifacts.write_json_artifact(dpath, self.director); artifacts.write_json_artifact(tpath, self.treatment)
        self.proposal = {'inputs': {'director': vc._record(self.root, dpath), 'treatment': vc._record(self.root, tpath)}}
        source = self.root / 'native-projects/native-test/index.html'
        source.parent.mkdir(parents=True); source.write_text('<html>输入</html>')
        call = self.root / 'native-inputs/call.json'
        artifacts.write_json_artifact(call, {'project_files': [native.descriptor(self.root, source)]})
        self.result = {'render_call': native.descriptor(self.root, call)}
        ref = {'path': source.relative_to(self.root).as_posix(), 'sha256': native.sha(source),
               'pointer': 'text:6:8', 'value': '输入'}
        self.target = {'target_id': 'native-input', 'content_ref': ref, 'span': [0, 2], 'role': 'title',
                       'region': {'x': 100, 'y': 200, 'width': 600, 'height': 100},
                       'windows': [{'start': .5, 'end': 1.5}]}

    def realized(self):
        director, treatment = copy.deepcopy(self.director), copy.deepcopy(self.treatment)
        director['segments'][0]['visible_text'] = ['输入']
        treatment['motion_readability'][0] = {'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [copy.deepcopy(self.target)]}
        return director, treatment

    def validate(self, director, treatment):
        with mock.patch.object(vc, '_native_result_adapter', return_value=self.native), \
             mock.patch.object(self.native, 'inspect_result', return_value=self.result):
            vc._validate_draft_against_source(self.root, self.proposal, director, treatment)

    def test_actual_native_text_can_be_added_but_semantics_time_and_numbering_cannot_change(self):
        director, treatment = self.realized(); self.validate(director, treatment)
        for change in ('semantic', 'time', 'template', 'numbering'):
            changed, altered = copy.deepcopy(director), copy.deepcopy(treatment)
            if change == 'semantic': altered['semantic_lists']['broll'][0]['semantic'] = '另一种意思'
            if change == 'time': changed['segments'][0]['end'] = 3
            if change == 'template': changed['segments'][0]['bindings']['component-1']['template_id'] = 'another-template'
            if change == 'numbering': altered['numbering_scope_id'] = 'another-scope'
            with self.subTest(change=change), self.assertRaises(ValueError): self.validate(changed, altered)

    def test_execution_revision_preserves_task_and_needs_current_binding_snapshot(self):
        director, treatment = self.realized()
        old = self.native.validate_brief((self.root / 'native-inputs/approved.json').read_bytes())
        revision = {**old, 'project_directory': 'native-projects/revision-2', 'result_record_path': 'native-inputs/revision-2.json'}
        path = self.root / 'native-inputs/revision-2-brief.json'; artifacts.write_json_artifact(path, revision)
        binding = director['segments'][0]['bindings']['component-1']; binding['brief_sha256'] = self.native.sha(path)
        binding['verification_id'] = __import__('hashlib').sha256((binding['source_sha256'] + binding['brief_sha256']).encode()).hexdigest()
        treatment['scenes'][0]['brief_path'] = 'native-inputs/revision-2-brief.json'
        with self.assertRaisesRegex(ValueError, 'failure reason'): self.validate(director, treatment)
        treatment['scenes'][0]['native_revision_reason'] = '首次实看发现文字遮挡，仅修订该项原生排版'
        with self.assertRaisesRegex(ValueError, 'snapshot'): self.validate(director, treatment)
        treatment['skill_selection']['beats'][0]['binding_snapshot'] = copy.deepcopy(binding)
        self.validate(director, treatment)
        revision['authorization'] = {'paid_generation': True}; artifacts.write_json_artifact(path, revision)
        binding['brief_sha256'] = self.native.sha(path)
        with self.assertRaisesRegex(ValueError, 'approved semantic task'): self.validate(director, treatment)

    def test_readability_rejects_foreign_source_and_preserves_user_confirmed_text(self):
        director, treatment = self.realized()
        treatment['motion_readability'][0]['targets'][0]['content_ref']['path'] = 'foreign.html'
        with self.assertRaisesRegex(ValueError, 'actual rendered project'): self.validate(director, treatment)
        director, treatment = self.realized()
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'segment_id': 'seg-002', 'component_id': 'component-1',
                         'visible_text': ['其他镜头指定']}]})
        self.validate(director, treatment)
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'segment_id': 'seg-001', 'component_id': 'component-1',
                         'visible_text': ['用户指定']}]})
        with self.assertRaisesRegex(ValueError, 'retain confirmed text'): self.validate(director, treatment)
        artifacts.write_json_artifact(self.root / 'manifests/confirmed-content.json',
            {'visuals': [{'component_id': 'component-1', 'visible_text': ['用户指定']}]})
        with self.assertRaisesRegex(ValueError, 'retain confirmed text'): self.validate(director, treatment)

    def test_sequential_native_revisions_preserve_earlier_completed_references(self):
        second=copy.deepcopy(self.director['segments'][0]);second['segment_id']='seg-002'
        second['start']=2;second['end']=4;self.director['segments'].append(second)
        request=self.native.validate_brief((self.root/'native-inputs/approved.json').read_bytes())
        request['source_binding'].update(segment_id='seg-002',start=2,end=4)
        request['task_source']['semantic_row_id']='semantic-2'
        request.update(project_directory='native-projects/second',result_record_path='native-inputs/second.json')
        path=self.root/'native-inputs/second-brief.json';artifacts.write_json_artifact(path,request)
        binding=second['bindings']['component-1'];binding['brief_sha256']=self.native.sha(path)
        binding['verification_id']=__import__('hashlib').sha256((binding['source_sha256']+binding['brief_sha256']).encode()).hexdigest()
        row=copy.deepcopy(self.treatment['semantic_lists']['broll'][0]);row['row_id']='semantic-2'
        row['components'][0]['segment_id']='seg-002';self.treatment['semantic_lists']['broll'].append(row)
        beat=copy.deepcopy(self.treatment['skill_selection']['beats'][0]);beat.update(segment_id='seg-002',semantic_row_id='semantic-2',binding_snapshot=copy.deepcopy(binding))
        self.treatment['skill_selection']['beats'].append(beat)
        for field in ('scenes','semantic_assessments','motion_readability'):
            item=copy.deepcopy(self.treatment[field][0]);item['segment_id']='seg-002'
            if field=='scenes':item['brief_path']='native-inputs/second-brief.json'
            self.treatment[field].append(item)
        for name,value in [('director',self.director),('treatment',self.treatment)]:
            path=self.root/('approved-'+name+'.json');artifacts.write_json_artifact(path,value)
            self.proposal['inputs'][name]=vc._record(self.root,path)
        director,treatment=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
        first_revision=None
        for index,scene in enumerate(treatment['scenes']):
            revision=self.native.validate_brief((self.root/scene['brief_path']).read_bytes())
            revision.update(project_directory=f'native-projects/revision-{index}',result_record_path=f'native-inputs/revision-{index}.json')
            path=self.root/f'native-inputs/revision-{index}-brief.json';artifacts.write_json_artifact(path,revision)
            scene.update(brief_path=path.relative_to(self.root).as_posix(),native_revision_reason='当前画面需修订')
            binding=director['segments'][index]['bindings']['component-1'];binding['brief_sha256']=self.native.sha(path)
            binding['verification_id']=__import__('hashlib').sha256((binding['source_sha256']+binding['brief_sha256']).encode()).hexdigest()
            treatment['skill_selection']['beats'][index]['binding_snapshot']=copy.deepcopy(binding)
            self.validate(director,treatment)
            if index==0:first_revision=copy.deepcopy(director['segments'][0])
            else:self.assertEqual(director['segments'][0],first_revision)

    def test_pending_native_text_is_only_a_planning_state(self):
        from edit.hd.tools import motion_readability
        segment = self.director['segments'][0]
        segments = [{**segment, 'shot_recipe': {'components': segment['visual_strategy']['components']}}]
        records = self.treatment['motion_readability']
        self.assertEqual(motion_readability.validate_targets(segments, records, [],
            pending_components={('seg-001', 'component-1')})[0]['status'], 'pending_native')
        with self.assertRaisesRegex(ValueError, 'only allowed'):
            motion_readability.validate_targets(segments, records, [])

    def test_generated_text_completion_preserves_approval_and_requires_actual_sources(self):
        frozen = copy.deepcopy(self.director)
        segment = frozen['segments'][0]
        segment['visible_text'] = ['输入']
        segment['bindings'] = {'component-1': {'dependency_id': 'paper-collage-ad', 'template_id': 'paper'}}
        old = copy.deepcopy(self.treatment)
        old['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                     'pending_generation': True}]
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {'prompt': 'approved paper'}, 'depends_on': []}
        old['generation_plan'] = {'steps': [step], 'cost_note': 'one approved image'}
        for name, data in [('director', frozen), ('treatment', old)]:
            path = self.root / ('approved-' + name + '.json'); artifacts.write_json_artifact(path, data)
            self.proposal['inputs'][name] = vc._record(self.root, path)
        self.proposal['generation_steps'] = [step]
        director, treatment = copy.deepcopy(frozen), copy.deepcopy(old)
        payload = {'source_binding': {'segment_id': 'seg-001', 'start': segment['start'], 'end': segment['end']},
                   'entry': {'job_path': self.target['content_ref']['path'], 'sha256': self.target['content_ref']['sha256']}}
        path = self.root / 'actual-brief.json'; artifacts.write_json_artifact(path, payload)
        director['segments'][0]['bindings']['component-1']['brief_sha256'] = artifacts.sha256_file(path)
        treatment['scenes'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'brief_path': path.name}]
        treatment['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                            'targets': [copy.deepcopy(self.target)]}]
        output = self.root / 'generated-output.bin'; output.write_bytes(b'fixture completed output')
        evidence = [{'step_id': 'image', 'media': [vc._record(self.root, output)]}]
        def validate(director, treatment, evidence=evidence, eligible={('seg-001', 'component-1')}):
            with mock.patch.object(vc, 'planned_generation_targets', return_value=eligible):
                vc._validate_draft_against_source(self.root, self.proposal, director, treatment,
                                                  generation_evidence=evidence)
        validate(director, treatment)
        for change in ('no_completion', 'not_eligible', 'wording', 'step_count', 'channel', 'cost',
                       'time', 'template', 'semantic', 'foreign_source', 'pending'):
            changed, altered = copy.deepcopy(director), copy.deepcopy(treatment)
            if change == 'no_completion':
                with self.assertRaisesRegex(ValueError, 'completed generation'): validate(changed, altered, [])
                continue
            if change == 'not_eligible':
                with self.assertRaisesRegex(ValueError, 'uncreated approved'): validate(changed, altered, eligible=set())
                continue
            if change == 'wording': changed['segments'][0]['visible_text'] = ['新文案']
            elif change == 'step_count': altered['generation_plan']['steps'].append({**step, 'id': 'extra'})
            elif change == 'channel': altered['generation_plan']['steps'][0]['arguments']['model'] = 'unapproved'
            elif change == 'cost': altered['generation_plan']['cost_note'] = 'two paid images'
            elif change == 'time': changed['segments'][0]['end'] += 1
            elif change == 'template': changed['segments'][0]['bindings']['component-1']['template_id'] = 'other'
            elif change == 'semantic': altered['semantic_lists']['broll'][0]['semantic'] = 'new fact'
            elif change == 'pending': altered['motion_readability'][0]['pending_generation'] = True
            else: altered['motion_readability'][0]['targets'][0]['content_ref']['path'] = 'foreign.html'
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)):
                validate(changed, altered)

    def test_approved_visible_text_cannot_be_removed_even_with_an_existing_target(self):
        self.director['segments'][0]['visible_text']=['输入']
        self.treatment['motion_readability'][0]={'segment_id':'seg-001','component_id':'component-1','targets':[self.target]}
        for name,value in [('director',self.director),('treatment',self.treatment)]:
            path=self.root/('approved-'+name+'.json');artifacts.write_json_artifact(path,value)
            self.proposal['inputs'][name]=vc._record(self.root,path)
        director,treatment=copy.deepcopy(self.director),copy.deepcopy(self.treatment)
        director['segments'][0]['visible_text']=[]
        treatment['motion_readability'][0]={'segment_id':'seg-001','component_id':'component-1','targets':[],
                                          'no_critical_text_reason':'不能以无字理由删除已批准文字'}
        with self.assertRaisesRegex(ValueError,'retain confirmed text'):self.validate(director,treatment)

    def test_generated_image_text_requires_scoped_real_image_and_human_review(self):
        from PIL import Image
        from edit.hd.tools import motion_capabilities
        image = self.root / 'actual-image.png'
        Image.new('RGB', (10, 10), 'white').save(image)
        image_ref = vc._record(self.root, image)
        brief = '报销单缺附件时停下，人的手补入附件。'
        component = {'component_id': 'component-1', 'kind': 'code_generated', 'brief': brief}
        original = {'segment_id': 'seg-001', 'start': 0, 'end': 2, 'visible_text': [],
                    'visual_strategy': {'components': [component]},
                    'bindings': {'component-1': {'brief_sha256': 'a' * 64}}}
        frozen = {'segments': [original]}
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {}, 'depends_on': []}
        old = {'motion_readability': [{'segment_id': 'seg-001', 'component_id': 'component-1',
                                      'pending_generation': True, 'targets': []}],
               'generation_plan': {'steps': [step]}}
        target = {'target_id': 'actual-image-title', 'content_ref': {
            'path': image_ref['path'], 'sha256': image_ref['sha256'], 'pointer': 'image-text', 'value': '费用报销单'},
            'span': [0, 5], 'role': 'body', 'region': {'x': 10, 'y': 10, 'width': 300, 'height': 80},
            'windows': [{'start': 0, 'end': 1}]}
        review = {'segment_id': 'seg-001', 'component_id': 'component-1', 'text': '费用报销单',
                  'source_quote': brief, 'source_image': image_ref, 'verdict': 'pass',
                  'reason': '宿主审阅：费用报销单是原确认报销单对象的标题。'}
        director = copy.deepcopy(frozen); director['segments'][0]['visible_text'] = ['费用报销单']
        treatment = copy.deepcopy(old); treatment['motion_readability'][0] = {
            'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [target]}
        treatment['reviewed_generated_text'] = [review]
        evidence = [{'step_id': 'image', 'media': [image_ref]}]
        def validate(d, t, *, comparison_director=None, comparison_treatment=None):
            with mock.patch.object(vc, 'planned_generation_targets', return_value={('seg-001', 'component-1')}), \
                 mock.patch.object(motion_capabilities, '_bound_brief', return_value={}) as bound, \
                 mock.patch.object(motion_capabilities, '_brief_relative', return_value='brief.json'):
                result = vc._validate_generated_readability(self.root, {'generation_steps': [step]},
                    frozen, old, comparison_director or d, comparison_treatment or t, evidence,
                    production_director=d, production_treatment=t)
                bound.assert_called_once_with(self.root, t, d['segments'][0], 'component-1')
                return result
        validate(copy.deepcopy(director), copy.deepcopy(treatment))
        # Deferred native routes lose their real bindings only in the comparison copy.
        comparison = copy.deepcopy(director)
        comparison['segments'][0]['bindings']['component-1'].pop('brief_sha256')
        validate(copy.deepcopy(director), copy.deepcopy(treatment), comparison_director=comparison)
        for mutation in ('missing_review', 'wrong_quote', 'wrong_image', 'unreviewed_new_fact', 'rejected_review'):
            d, t = copy.deepcopy(director), copy.deepcopy(treatment)
            if mutation == 'missing_review': t['reviewed_generated_text'] = []
            elif mutation == 'wrong_quote': t['reviewed_generated_text'][0]['source_quote'] = '无来源的另一项任务'
            elif mutation == 'wrong_image': t['reviewed_generated_text'][0]['source_image']['sha256'] = 'b' * 64
            elif mutation == 'rejected_review': t['reviewed_generated_text'][0]['verdict'] = 'fail'
            else: d['segments'][0]['visible_text'].append('报销已完成')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): validate(d, t)

    def test_deferred_generation_can_bind_real_parent_static_labels_without_replanning(self):
        from edit.hd.tests.test_segment_render_components import ParentStaticLabelTests
        from edit.hd.tools import motion_capabilities
        segment, label, png = ParentStaticLabelTests().fixture(self.root)
        segment.update(segment_id='seg-001', end=2)
        segment['bindings']['component-1'] = segment['bindings'].pop('visual-1')
        binding = segment['bindings']['component-1']
        manifest_path = self.root / binding['parent_static_labels']['job_path']
        manifest = artifacts.read_json_artifact(manifest_path)
        manifest.update(segment_id='seg-001', component_id='component-1')
        artifacts.write_json_artifact(manifest_path, manifest)
        binding['parent_static_labels'].update(sha256=artifacts.sha256_file(manifest_path),
                                               byte_count=manifest_path.stat().st_size)
        frozen = copy.deepcopy(self.director)
        frozen['segments'][0]['visible_text'] = ['聊天']
        frozen['segments'][0]['visual_strategy']['components'][0]['kind'] = 'ai_generated'
        frozen['segments'][0]['bindings'] = {'component-1': {'provider': 'fixture', 'model': 'fixture', 'endpoint_id': 'fixture'}}
        old = copy.deepcopy(self.treatment)
        old['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'pending_generation': True}]
        step = {'id': 'image', 'purpose': 'image', 'segment_id': 'seg-001', 'component_id': 'component-1',
                'arguments': {'prompt': 'approved scene with parent labels'}, 'depends_on': []}
        old['generation_plan'] = {'steps': [step], 'cost_note': 'one image'}
        self.proposal['generation_steps'] = [step]
        for name, value in [('director', frozen), ('treatment', old)]:
            path = self.root / ('approved-' + name + '.json'); artifacts.write_json_artifact(path, value)
            self.proposal['inputs'][name] = vc._record(self.root, path)
        director, treatment = copy.deepcopy(frozen), copy.deepcopy(old)
        director['segments'][0]['bindings']['component-1'].update(binding)
        target = {'target_id': 'parent-chat-label', 'content_ref': label['content_ref'], 'span': [0, 2], 'role': 'body',
                  'region': {'x': 120, 'y': 180, 'width': 240, 'height': 96}, 'windows': [{'start': .25, 'end': .75}]}
        treatment['motion_readability'] = [{'segment_id': 'seg-001', 'component_id': 'component-1', 'targets': [target]}]
        evidence = [{'step_id': 'image', 'media': [vc._record(self.root, png)]}]
        with mock.patch.object(vc, 'planned_generation_targets', return_value={('seg-001', 'component-1')}), \
             mock.patch.object(motion_capabilities, '_ai_brief_evidence',
                               return_value=({'observed_scene': 'fixture'}, {'job_path': 'completed.json', 'sha256': 'a' * 64})):
            vc._validate_draft_against_source(self.root, self.proposal, director, treatment, generation_evidence=evidence)
            # Exercise the final persisted mapping consumer, not just its draft gate.
            director['segments'][0]['bindings']['component-1']['sha256'] = artifacts.sha256_file(png)
            config = self.root / 'manifests/provider-config.json'; artifacts.write_json_artifact(config, {})
            self.proposal.update(job_id='job', kind=vc.SCHEMA, rows=[], provider_config_sha256=artifacts.sha256_file(config))
            proposal_path = self.root / 'proposal.json'; artifacts.write_json_artifact(proposal_path, self.proposal)
            receipt = {'source_schema': vc.SCHEMA, 'job_id': 'job', 'job_dir': str(self.root),
                'stage': 'visual_direction', 'passed': True, 'reviewed_by': 'human', 'revision': 1,
                'approval_scope': 'visual_plan_and_delivery', 'note': 'synthetic test',
                'user_confirmation': 'fixture approval', 'artifacts': [], 'source': vc._record(self.root, proposal_path)}
            receipt_path = self.root / 'receipt.json'; artifacts.write_json_artifact(receipt_path, receipt)
            receipt_ref = vc._record(self.root, receipt_path)
            realized = {}
            for name, value in [('director', director), ('treatment', treatment)]:
                path = self.root / ('realized-' + name + '.json'); artifacts.write_json_artifact(path, value)
                realized[name] = vc._record(self.root, path)
            final = copy.deepcopy(director)
            compiled = {k: v for k, v in director['segments'][0]['bindings']['component-1'].items()
                        if k not in {'execution_mode', 'media_type', 'source_dimensions', 'parent_static_labels'}}
            final['segments'][0]['shot_recipe'] = {'components': [{'component_id': 'component-1', **compiled}]}
            final_path = self.root / 'final.json'
            def consume():
                artifacts.write_json_artifact(final_path, final)
                final_ref = vc._record(self.root, final_path)
                mapping = {'source_approval': receipt_ref, 'proposal': receipt['source'], 'host_qa_note': 'fixture',
                    'artifacts': [final_ref], 'final_v3': final_ref, 'rows': [], 'realization_inputs': realized,
                    'generations': [{**evidence[0], 'request_id': 'fixture-image', 'request': {'input_files': []}}]}
                path = self.root / '07-visual-direction' / vc.MAPPING; artifacts.write_json_artifact(path, mapping)
                stages = {'visual_direction': {'artifacts': [final_ref, vc._record(self.root, path)]}}
                return vc.validate_realization_evidence(self.root, stages, 2, receipt_ref, job_id='job')
            self.assertIn('mapping', consume())
            final['segments'][0]['shot_recipe']['components'][0]['provider'] = 'unapproved-provider'
            with self.assertRaisesRegex(ValueError, 'compiled template differs'):
                consume()
            director['segments'][0]['start'] += .25
            with self.assertRaisesRegex(ValueError, 'timing, meaning'):
                vc._validate_draft_against_source(self.root, self.proposal, director, treatment, generation_evidence=evidence)

    def test_frozen_realization_cannot_be_overwritten_before_stage_revision(self):
        from types import SimpleNamespace
        job=SimpleNamespace(stages={'visual_direction':{'status':'approved','artifacts':[]}})
        with self.assertRaisesRegex(ValueError,'frozen'):
            vc.write_realization_mapping(job,host_qa_note='不能覆盖已审结果',director_path=None,treatment_path=None)

    def test_realization_mappings_are_immutable_and_unique_per_revision(self):
        old = self.root / '07-visual-confirmation' / 'r26-approved' / vc.MAPPING
        artifacts.write_json_artifact(old, {'original': True})
        old_bytes = old.read_bytes()
        first = vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        again = vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        later = vc._write_unique_mapping(self.root, 35, {'approval': 'same', 'plan': 'second'})
        self.assertEqual(first, again)
        self.assertNotEqual(first, later)
        self.assertEqual(old.read_bytes(), old_bytes)
        first.write_bytes(b'not the approved mapping')
        with self.assertRaisesRegex(ValueError, 'differs'):
            vc._write_unique_mapping(self.root, 33, {'approval': 'same', 'plan': 'first'})
        self.assertEqual(first.read_bytes(), b'not the approved mapping')

    def test_realization_writer_retains_old_mapping_and_source_approval(self):
        from edit.hd.tools import state
        from types import SimpleNamespace
        old = self.root / '07-visual-confirmation' / 'r26-approved' / vc.MAPPING
        artifacts.write_json_artifact(old, {'original': True}); old_bytes = old.read_bytes()
        plan = self.root / '07-visual-direction' / 'visual-plan.json'
        artifacts.write_json_artifact(plan, {'segments': []})
        director = self.root / 'director.json'; treatment = self.root / 'treatment.json'
        artifacts.write_json_artifact(director, {'segments': []})
        artifacts.write_json_artifact(treatment, {'scenes': []})
        approval = {'path': 'manifests/user-confirmation.json', 'sha256': 'a' * 64, 'bytes': 1}
        source = {'path': '07-visual-confirmation/r26-approved/proposal.json', 'sha256': 'b' * 64, 'bytes': 1}
        job = SimpleNamespace(job_dir=self.root, revision=35, stages={'visual_direction': {
            'status': 'ready_for_review', 'artifacts': [vc._record(self.root, plan)]}})
        with mock.patch.object(vc, 'validate_visual_authorization', return_value={
                'artifact': approval, 'payload': {'source': source}, 'source': {'rows': []}}), \
             mock.patch.object(vc, '_completed_generations', return_value=[]), \
             mock.patch.object(state, 'mark_visual_ready') as ready:
            path = vc.write_realization_mapping(job, host_qa_note='已核验', director_path=director, treatment_path=treatment)
        self.assertNotEqual(path, old)
        self.assertEqual(old.read_bytes(), old_bytes)
        mapping = vc._read(path)
        self.assertEqual(mapping['source_approval'], approval)
        self.assertEqual(mapping['proposal'], source)
        self.assertEqual(mapping['final_v3'], vc._record(self.root, plan))
        ready.assert_called_once()


class OfficialPortraitCropTests(unittest.TestCase):
    def test_supplement_keeps_one_original_routing_number(self):
        from edit.hd.tools import visual_plan
        segment = {'segment_id': 'seg-001', 'start': 0, 'end': 2,
            'visual_intent': {'statement': '原任务'}, 'visual_strategy': {'mode': 'hybrid', 'components': [
                {'component_id': 'base', 'kind': 'ai_generated', 'layer_role': 'base'},
                {'component_id': 'action', 'kind': 'code_generated', 'layer_role': 'annotation'}]},
            'bindings': {'base': {'template_id': 'original/design'}, 'action': {'template_id': 'barty/motion-broll'}}}
        selection = {'native_supplements': [{'segment_id': 'seg-001',
            'base_component_id': 'base', 'action_component_id': 'action'}]}
        text = visual_plan._review_text({'segments': [segment]}, skill_selection=selection,
                                       numbering={'seg-001:base': 2})
        self.assertEqual(text.count('| 2 |'), 1)
        self.assertIn('original/design + barty/motion-broll（同项补足层）', text)
        self.assertNotIn('| 3 |', text)

    def test_approved_task_example_cannot_add_numbers_or_claim_evidence(self):
        from edit.hd.tools import visual_plan
        quote = '示意邮件包含项目沟通，周五15:00；持续标注任务示意。'
        component = {'component_id': 'native', 'kind': 'code_generated',
                     'semantic_role': 'explanation', 'brief': quote}
        segment = {'segment_id': 'seg-001', 'visible_text': ['任务示意', '周五 15:00'],
                   'visual_strategy': {'components': [component]}}
        analysis = {'analysis_sha256': 'a' * 64, 'analysis': {'thesis': '整理日程', 'items': []}}
        record = {'content_analysis_sha256': 'a' * 64, 'entries': [{
            'segment_id': 'seg-001', 'text': '周五 15:00', 'source_ref': 'component:native',
            'source_quote': quote, 'reason': '沿已确认示例保留同一时间，不声称真实执行。'}]}
        visual_plan._validate_reviewed_visual_text(record, analysis_record=analysis, segments=[segment])
        for change in ('number', 'evidence', 'unmarked'):
            actual, review = copy.deepcopy(segment), copy.deepcopy(record)
            if change == 'number':
                actual['visible_text'][1] = review['entries'][0]['text'] = '周五 16:00'
            elif change == 'evidence': actual['visual_strategy']['components'][0]['semantic_role'] = 'evidence'
            else: actual['visible_text'].remove('任务示意')
            with self.subTest(change=change), self.assertRaises(visual_plan.VisualPlanError):
                visual_plan._validate_reviewed_visual_text(review, analysis_record=analysis, segments=[actual])

    def test_same_source_crop_renders_exact_portrait_without_changing_native_gate(self):
        import tempfile
        import shutil
        from types import SimpleNamespace
        from PIL import Image
        from edit.hd.tools import broll_component_executor, material_adapter, visual_strategy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'official.png'
            original = Image.new('RGB', (320, 160), 'blue')
            original.paste('red', (0, 0, 90, 160)); original.save(source)
            digest = artifacts.sha256_file(source)
            binding = {'source_id': 'official', 'sha256': digest, 'snapshot_path': 'official.png',
                'portrait_crop': {'source_sha256': digest, 'source_width': 320, 'source_height': 160,
                                  'x': 0, 'y': 0, 'width': 90, 'height': 160}}
            candidate = {'asset_id': 'official', 'kind': 'official_material', 'quality_score': 1,
                'semantic_match_score': 1, 'hard_gates': {'native_vertical': False,
                'semantic_match': True, 'quality_readability': True, 'factual_reliability': True}}
            with self.assertRaises(ValueError):
                visual_strategy.stable_same_kind_candidates([candidate], 'official_material')
            ranked = visual_strategy.stable_same_kind_candidates([candidate], 'official_material', framing_binding=binding)
            self.assertFalse(ranked[0]['hard_gates']['native_vertical'])
            component = {**binding, 'artifact_contract': {'width': 1080, 'height': 1920, 'fps': 24, 'alpha': False}}
            output = root / 'portrait.png'
            context = SimpleNamespace(source_path=source, source_sha256=digest,
                                      component=broll_component_executor._freeze(component), staging_path=output)
            adapter = material_adapter.create_adapter('official_material', 'image', shutil.which('ffmpeg'), shutil.which('ffprobe'))
            result = adapter.invoke(context)
            broll_component_executor._validate_adapter_result(result, 'BROLL_COMPOSITE_FAILED',
                                                               job_dir=root, request_only_values=())
            with Image.open(output) as actual:
                self.assertEqual(actual.size, (1080, 1920))
                self.assertEqual(actual.tobytes(), original.crop((0, 0, 90, 160)).resize((1080, 1920), Image.Resampling.LANCZOS).tobytes())
            self.assertEqual(artifacts.sha256_file(source), digest)
            self.assertEqual(result.invocation_evidence['portrait_crop'], binding['portrait_crop'])
            for change in ('outside', 'source', 'quality'):
                bad_binding, bad_candidate = copy.deepcopy(binding), copy.deepcopy(candidate)
                if change == 'outside': bad_binding['portrait_crop']['x'] = 300
                elif change == 'source': bad_binding['portrait_crop']['source_sha256'] = 'b' * 64
                else: bad_candidate['hard_gates']['quality_readability'] = False
                with self.subTest(change=change), self.assertRaises(ValueError):
                    visual_strategy.stable_same_kind_candidates([bad_candidate], 'official_material', framing_binding=bad_binding)
            old_binding = {k: v for k, v in binding.items() if k != 'portrait_crop'}
            segment = {'segment_id': 'seg-001', 'visual_strategy': {'components': [
                {'component_id': 'image', 'kind': 'official_material', 'media_type': 'image'}]}, 'bindings': {'image': old_binding}}
            frozen = {'segments': [segment]}; director = copy.deepcopy(frozen)
            director['segments'][0]['bindings']['image'] = binding
            before = {'motion_readability': [{'segment_id': 'seg-001', 'component_id': 'image', 'targets': [
                {'target_id': 'model', 'content_ref': {'value': 'model'}, 'region': {'x': 0, 'y': 0, 'width': 100, 'height': 100}}]}]}
            after = copy.deepcopy(before); after['motion_readability'][0]['targets'][0]['region']['width'] = 200
            self.assertEqual(vc._normalize_official_crop_text(root, frozen, before, director, after, after), before)
            after['motion_readability'][0]['targets'][0]['content_ref']['value'] = 'different model'
            with self.assertRaises(ValueError):
                vc._normalize_official_crop_text(root, frozen, before, director, after, after)


class OpenfilmTypographyTests(unittest.TestCase):
    def test_only_existing_css_font_sizes_can_increase(self):
        from edit.hd.tools import visual_confirmation as vc
        source = '<style>.label{font-size:36px}.row{font-size:37px}</style><p>原字</p><script>frame(1)</script>'
        revised = source.replace('36px','42px').replace('37px','44px')
        vc._validate_css_font_growth(source,revised)
        for invalid in (source, source.replace('36px','32px'), revised.replace('原字','新字'),
                        revised.replace('frame(1)','frame(2)'), revised.replace('44px','144px'),
                        revised.replace('.row{','.row{display:none;')):
            with self.subTest(invalid=invalid), self.assertRaises(vc.VisualConfirmationError):
                vc._validate_css_font_growth(source,invalid)


if __name__ == "__main__":
    unittest.main()

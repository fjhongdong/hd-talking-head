import hashlib
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edit.hd.tools import visual_review


class VisualReviewPlanIdentityTests(unittest.TestCase):
    def user_preview(self):
        media = {'path': '11-preview/review.mp4', 'sha256': 'current', 'bytes': 123}
        expected = {'status': 'required', 'policy_version': visual_review.POLICY_VERSION,
                    'stage': 'preview', 'plan_ref': {'path': 'plan.json', 'sha256': 'plan', 'bytes': 10},
                    'observations': [{'row_id': 'seg-001:visual', 'media_ref': media,
                                      'media_duration': 3.0, 'window': [0.0, 3.0]}]}
        reply = '这条样片我已从头到尾看完并听完，画面和声音通过。'
        review = {'reviewed_by': 'user', 'user_confirmation': reply,
                  'full_playback_reviewed': True, 'audio_listened': True,
                  'visual_review': {'policy_version': expected['policy_version'], 'stage': 'preview',
                      'plan_ref': expected['plan_ref'], 'observations': [{
                          'row_id': 'seg-001:visual', 'media_ref': media, 'playback_window': [0.0, 3.0],
                          'conclusion': reply, 'size_position_clear': True,
                          'unobstructed': True, 'semantics_clear': True,
                          'design_review': {'verdict': 'pass', **{name: reply for name in
                              ('composition', 'typography', 'finish', 'focus')}}}]}}
        return expected, review

    def test_user_preview_requires_reply_flags_and_complete_current_media(self):
        expected, review = self.user_preview()
        job = SimpleNamespace(stages={'preview': {'status': 'ready_for_review'}})
        with patch.object(visual_review, 'expected_observations', return_value=expected):
            self.assertEqual(visual_review.validate_stage_review(job, 'preview', review), review['visual_review'])
            for changes in ({'user_confirmation': ''}, {'audio_listened': False},
                            {'full_playback_reviewed': False}, {'audio_listened': 1},
                            {'user_confirmation': '继续', 'audio_listened': False,
                             'full_playback_reviewed': False}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    visual_review.validate_stage_review(job, 'preview', {**review, **changes})
            for change in ('media', 'plan', 'window', 'missing_component'):
                altered = copy.deepcopy(review)
                payload = altered['visual_review']
                if change == 'media': payload['observations'][0]['media_ref']['sha256'] = 'stale'
                elif change == 'plan': payload['plan_ref']['sha256'] = 'stale'
                elif change == 'window': payload['observations'][0]['playback_window'] = [1.0, 3.0]
                else: payload['observations'] = []
                with self.subTest(change=change), self.assertRaises(ValueError):
                    visual_review.validate_stage_review(job, 'preview', altered)

    def test_delivery_reads_true_user_review_without_relabeling_host_receipts(self):
        expected, review = self.user_preview()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'manifests').mkdir()
            records = [expected['observations'][0]['media_ref']]
            job = SimpleNamespace(job_id='j', job_dir=root,
                                  stages={'preview': {'status': 'approved', 'artifacts': records}})
            receipt = {**review, 'job_id': 'j', 'job_dir': str(root), 'stage': 'preview',
                       'passed': True, 'artifacts': records}
            path = root / 'manifests/local-qa-preview-r1.json'
            with patch.object(visual_review, 'expected_observations', return_value=expected):
                path.write_text(json.dumps(receipt))
                visual_review.require_preview_review(job)
                altered = copy.deepcopy(receipt); altered['artifacts'][0]['sha256'] = 'stale'
                path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError): visual_review.require_preview_review(job)
                # Frozen host observations continue under their existing contract.
                host = {k: v for k, v in receipt.items() if k not in
                        {'user_confirmation', 'full_playback_reviewed', 'audio_listened'}}
                host['reviewed_by'] = 'host'; path.write_text(json.dumps(host))
                visual_review.require_preview_review(job)

    def test_explicit_user_final_review_preserves_unchecked_state(self):
        expected = {"status": "required", "policy_version": "visual-review-v2",
                    "stage": "preview", "plan_ref": {"sha256": "current"},
                    "observations": [{"row_id": "seg-001:visual"}]}
        pending = {"status": "pending", "user_instruction": "先继续合成完整视频，完成后发给我，我来检查画面和声音",
                   "full_playback_reviewed": False, "audio_listened": False,
                   "expected_media": expected}
        with patch.object(visual_review, "expected_observations", return_value=expected):
            result = visual_review.validate_stage_review(None, "preview", {"user_final_review": pending})
            self.assertEqual(result["status"], "user_review_pending")
            visual_review.validate_stage_review(None, "preview", {"user_final_review": pending,
                                                                 "visual_review": result})
            for changed in ({"audio_listened": True}, {"expected_media": {}}, {"user_instruction": ""}):
                with self.assertRaises(ValueError):
                    visual_review.validate_stage_review(None, "preview", {"user_final_review": {**pending, **changed}})

    def test_manifest_uses_content_identity_while_files_stay_hash_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def write(relative, value):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, sort_keys=True, indent=2))
                return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "bytes": path.stat().st_size}
            segment = {"segment_id": "seg-001", "start": 0, "end": 1,
                       "visual_intent": {"statement": "one visible action"},
                       "shot_recipe": {"components": [{"component_id": "visual",
                           "render_window": {"start_frame": 0, "end_frame": 24}}]}}
            plan = {"duration": 1, "segments": [segment]}
            content_sha = hashlib.sha256(json.dumps(plan, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            plan["visual_plan_sha256"] = content_sha
            plan_ref = write("07-visual-direction/visual-plan.json", plan)
            self.assertNotEqual(content_sha, plan_ref["sha256"])
            media = write("08-visual-canary/segments/seg-001/segment.mp4", {})
            job = SimpleNamespace(job_dir=root, stages={"visual_canary": {"artifacts": []}})
            authorization = {"source": {"visual_review_policy": visual_review.POLICY_VERSION},
                             "mapping": {"final_v3": plan_ref}}
            for identity, valid in ((content_sha, True), (plan_ref["sha256"], False)):
                with self.subTest(manifest_identity=identity):
                    manifest = {"visual_plan_sha256": identity, "segment_ids": ["seg-001"],
                                "segments": [{"segment_id": "seg-001", "video_path": media["path"],
                                    "video_sha256": media["sha256"], "video_bytes": media["bytes"]}]}
                    manifest_ref = write("08-visual-canary/canary-manifest.json", manifest)
                    job.stages["visual_canary"]["artifacts"] = [manifest_ref, media]
                    with patch.object(visual_review.confirmation, "validate_visual_authorization",
                                      return_value=authorization):
                        if valid:
                            result = visual_review.expected_observations(job, "visual_canary")
                            self.assertEqual(result["plan_ref"], plan_ref)
                            self.assertEqual(len(result["observations"]), 1)
                        else:
                            with self.assertRaisesRegex(ValueError, "belongs to another plan"):
                                visual_review.expected_observations(job, "visual_canary")

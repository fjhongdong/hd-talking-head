import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from edit.hd.tools import visual_review


class VisualReviewPlanIdentityTests(unittest.TestCase):
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

import copy, json, shutil, tempfile, unittest, hashlib, subprocess
from unittest import mock
from pathlib import Path
from edit.hd.tools import content_analysis, state
from edit.hd.tools.relation_motion_maintenance import build_approved_relation_brief, RelationMotionMaintenanceError
from edit.hd.tests import test_content_analysis as ca
from edit.hd.tests.test_semantic_motion import draft

class RelationMotionMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.fx = ca.ContentAnalysisTests(); self.fx.setUp(); self.addCleanup(self.fx.tearDown)
        content_analysis.prepare_content_analysis(self.fx.job, ca.VALID_ANALYSIS); state.approve(self.fx.job, "content_analysis")
        self.draft = draft(); self.draft.update(content_item_id="idea-01", source_text=ca.SOURCE_TEXT)
        self.draft["subjects"].insert(1, {"id":"source2","label":"细节二","initial_state":"隐藏","final_state":"已显示","preserve":False})
        self.draft["actions"][0]["subject_ids"] = ["source", "source2"]
        self.draft["actions"][1]["subject_ids"] = ["source", "source2", "hub"]
    def test_approved_brief_is_strict_and_does_not_write_job(self):
        before = {p: p.read_bytes() for p in self.fx.job.job_dir.rglob('*') if p.is_file()}
        out = build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source", "source2"], "hub", shutil.which("node"))
        self.assertEqual(out["status"], "maintenance_only"); self.assertEqual(out["brief"]["schema_version"], 1)
        self.assertEqual(set(out["brief"]), {"schema_version", "canvas", "motion", "title", "source_ids", "hub_id"})
        canonical = json.dumps(out["brief"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(out["brief_sha256"], hashlib.sha256(canonical).hexdigest())
        html = subprocess.run([shutil.which("node"), str(Path(__file__).parents[1] / "tools/relation_motion_renderer.cjs"), "--html"], input=json.dumps(out["brief"]), text=True, capture_output=True)
        self.assertEqual(html.returncode, 0, html.stderr)
        after = {p: p.read_bytes() for p in self.fx.job.job_dir.rglob('*') if p.is_file()}; self.assertEqual(before, after)
    def test_unapproved_or_invalid_subjects_fail_without_write(self):
        with self.assertRaises(RelationMotionMaintenanceError): build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source"], "hub", shutil.which("node"))
        fresh = state.load_job(self.fx.job.job_dir); state.revise(fresh, "content_analysis", "revoke")
        with self.assertRaises(ca.content_analysis.ContentAnalysisError): build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source", "source2"], "hub", shutil.which("node"))
    def test_node_validation_failure_is_controlled(self):
        with self.assertRaises(RelationMotionMaintenanceError): build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source", "source2"], "hub", "/bin/false")

    def test_second_approval_report_drift_is_rejected(self):
        real = __import__("edit.hd.tools.semantic_motion", fromlist=["plan_motion_for_job"]).plan_motion_for_job(self.fx.job, self.draft)
        altered = dict(real, content_analysis_sha256="f" * 64)
        with mock.patch("edit.hd.tools.relation_motion_maintenance.semantic_motion.plan_motion_for_job", side_effect=[real, altered]):
            with self.assertRaises(RelationMotionMaintenanceError): build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source", "source2"], "hub", shutil.which("node"))

    def test_final_renderer_hash_drift_is_rejected(self):
        import edit.hd.tools.relation_motion_maintenance as module
        with mock.patch.object(module, "_sha", side_effect=["a" * 64, "a" * 64, "b" * 64]):
            with self.assertRaises(RelationMotionMaintenanceError): build_approved_relation_brief(self.fx.job.job_dir, self.draft, "关系图", ["source", "source2"], "hub", shutil.which("node"))

if __name__ == '__main__': unittest.main()

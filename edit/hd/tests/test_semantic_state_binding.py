import copy
import importlib
import json
import hashlib
import unittest
from unittest.mock import patch

from edit.hd.tests.test_semantic_state_renderer import brief

with open("/usr/local/bin/node", "rb") as node:
    digest = hashlib.sha256()
    for block in iter(lambda: node.read(65536), b""):
        digest.update(block)
NODE_SHA = digest.hexdigest()


class SemanticBindingTests(unittest.TestCase):
    def test_actual_job_approval_and_revocation_are_read_only(self):
        from edit.hd.tests import test_content_analysis as fixture_module
        from edit.hd.tools import content_analysis, state
        from edit.hd.tools.semantic_state_binding import bind_brief
        fixture = fixture_module.ContentAnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        content_analysis.prepare_content_analysis(fixture.job, fixture_module.VALID_ANALYSIS)
        value = brief("threshold")
        value["motion"].update(content_item_id="idea-01", source_text=fixture_module.SOURCE_TEXT)
        payload = json.dumps(value).encode()
        def bind():
            return bind_brief(fixture.job, payload, node_executable="/usr/local/bin/node", node_sha256=NODE_SHA,
                              template_id="hd-talking-head/semantic-state-threshold")
        with self.assertRaises(content_analysis.ContentAnalysisError):
            bind()
        state.approve(fixture.job, "content_analysis")
        before = {str(p): p.read_bytes() for p in fixture.job.job_dir.rglob("*") if p.is_file()}
        self.assertEqual(bind()["semantic_motion"]["plan"], value["motion"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in fixture.job.job_dir.rglob("*") if p.is_file()})
        state.revise(state.load_job(fixture.job.job_dir), "content_analysis", "test withdrawal")
        with self.assertRaises(content_analysis.ContentAnalysisError):
            bind()

    def test_each_family_binds_current_plan_and_rejects_wrong_template(self):
        name = "edit.hd.tools.semantic_state_binding"
        self.assertIsNotNone(importlib.util.find_spec(name), "semantic binding missing")
        module = importlib.import_module(name)
        for family in ("replacement", "threshold", "delay", "hierarchy", "feedback"):
            with self.subTest(family=family):
                value = brief(family)
                report = {"execution_status": "planning_only", "plan": value["motion"]}
                template = "hd-talking-head/semantic-state-" + family
                with patch.object(module.semantic_motion, "plan_motion_for_job", return_value=report):
                    result = module.bind_brief("job", json.dumps(value).encode(), node_executable="/usr/local/bin/node", node_sha256=NODE_SHA,
                                               template_id=template)
                    self.assertEqual(result["semantic_motion"], report)
                    self.assertEqual(result["template_request"], {"semantic_family": family,
                        "information_units": len(value["motion"]["subjects"]),
                        "numeric_values": [], "numeric_scale": "not_applicable"})
                    with self.assertRaisesRegex(ValueError, "template"):
                        module.bind_brief("job", json.dumps(value).encode(), node_executable="/usr/local/bin/node", node_sha256=NODE_SHA,
                                          template_id="hd-talking-head/semantic-state-wrong")
                    changed = copy.deepcopy(report)
                    changed["plan"]["source_text"] = "not the approved source"
                    with patch.object(module.semantic_motion, "plan_motion_for_job", return_value=changed):
                        with self.assertRaisesRegex(ValueError, "approved"):
                            module.bind_brief("job", json.dumps(value).encode(), node_executable="/usr/local/bin/node", node_sha256=NODE_SHA,
                                              template_id=template)

    def test_bad_roles_are_rejected_by_actual_renderer(self):
        name = "edit.hd.tools.semantic_state_binding"
        self.assertIsNotNone(importlib.util.find_spec(name), "semantic binding missing")
        module = importlib.import_module(name)
        value = brief()
        value["roles"] = {}
        with patch.object(module.semantic_motion, "plan_motion_for_job") as planner:
            with self.assertRaises(ValueError):
                module.bind_brief("job", json.dumps(value).encode(), node_executable="/usr/local/bin/node", node_sha256=NODE_SHA,
                                  template_id="hd-talking-head/semantic-state-replacement")
            planner.assert_not_called()

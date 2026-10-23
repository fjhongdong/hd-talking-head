import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "edit/hd/tools/relation_motion_renderer.cjs"


def plan(source_count=2, *, timing=(0, 12, 24, 36), family="relation"):
    source_ids = [f"s{i}" for i in range(source_count)]
    subjects = [
        {"id": item, "label": f"来源{i}", "initial_state": "隐藏", "final_state": "已显示", "preserve": False}
        for i, item in enumerate(source_ids)
    ]
    subjects.append({"id": "hub", "label": "汇聚", "initial_state": "隐藏", "final_state": "已形成", "preserve": False})
    start, draw, hub, read = timing
    return {
        "version": 1, "content_item_id": "item-1", "source_text": "批准原文",
        "family": family, "meaningful_change": "来源汇聚形成关系",
        "subjects": subjects,
        "actions": [
            {"id": "sources", "operation": "reveal_sources", "subject_ids": source_ids, "start_frame": start, "end_frame": draw, "depends_on": []},
            {"id": "connections", "operation": "draw_connections", "subject_ids": source_ids + ["hub"], "start_frame": draw, "end_frame": hub, "depends_on": ["sources"]},
            {"id": "hub", "operation": "reveal_hub", "subject_ids": ["hub"], "start_frame": hub, "end_frame": read, "depends_on": ["connections"]},
        ],
        "duration_frames": 120,
        "read_window": {"start_frame": read, "end_frame": 108, "minimum_frames": 24},
        "exit_window": {"start_frame": 108, "end_frame": 120},
    }


def brief(source_count=2, **kwargs):
    p = plan(source_count, **kwargs)
    return {"schema_version": 1, "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 120},
            "motion": p, "title": "关系图 <测试>", "source_ids": [s["id"] for s in p["subjects"] if s["id"] != "hub"], "hub_id": "hub"}


class RelationMotionRendererTests(unittest.TestCase):
    def run_node(self, *args, payload=None):
        return subprocess.run(["node", str(RENDERER), *args], input=None if payload is None else json.dumps(payload), text=True, capture_output=True, timeout=10)

    def test_validate_and_frame_state_follow_three_phases(self):
        result = self.run_node("--validate", payload=brief(3))
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = json.loads(result.stdout)
        self.assertEqual(checked["source_ids"], ["s0", "s1", "s2"])
        for frame, source_opacity, line, hub, alpha in ((0, 0, 0, 0, 1), (6, .5, 0, 0, 1), (11, 11/12, 0, 0, 1), (12, 1, 0, 0, 1), (18, 1, .5, 0, 1), (23, 1, 11/12, 0, 1), (24, 1, 1, 0, 1), (30, 1, 1, .5, 1), (35, 1, 1, 11/12, 1), (36, 1, 1, 1, 1), (72, 1, 1, 1, 1), (107, 1, 1, 1, 1), (108, 1, 1, 1, 1), (114, 1, 1, 1, 5/11), (119, 1, 1, 1, 0), (120, 1, 1, 1, 0)):
            state = self.run_node("--state", str(frame), payload=brief(3))
            self.assertEqual(state.returncode, 0, state.stderr)
            value = json.loads(state.stdout)
            self.assertAlmostEqual(value["source_progress"], source_opacity)
            self.assertEqual(value["connector_progress"], line)
            self.assertAlmostEqual(value["hub_progress"], hub)
            self.assertAlmostEqual(value["compositor_alpha"], alpha)
            self.assertEqual(value["artifact_alpha"], 1)
        self.assertNotEqual(self.run_node("--state", "11", payload=brief(2)).stdout, self.run_node("--state", "11", payload=brief(2, timing=(0, 20, 40, 60))).stdout)

    def test_html_is_escaped_self_contained_and_exposes_seek_frame(self):
        value = brief(2); value["motion"]["source_text"] = "</script><script>globalThis.pwned=1</script>SOURCE_SENTINEL"
        result = self.run_node("--html", payload=value)
        self.assertEqual(result.returncode, 0, result.stderr)
        class VisibleText(HTMLParser):
            def __init__(self): super().__init__(); self.hidden = 0; self.text = []
            def handle_starttag(self, tag, attrs): self.hidden += tag in {"script", "style", "title"}
            def handle_endtag(self, tag): self.hidden -= tag in {"script", "style", "title"}
            def handle_data(self, data):
                if not self.hidden: self.text.append(data)
        parser = VisibleText(); parser.feed(result.stdout)
        self.assertNotIn("SOURCE_SENTINEL", "".join(parser.text))
        self.assertNotIn("</script><script>", result.stdout)
        self.assertIn("function seekFrame", result.stdout)
        self.assertIn("line-height:1.5", result.stdout)
        self.assertNotRegex(result.stdout, r"https?://|src=\"//")
        self.assertEqual(result.stdout, self.run_node("--html", payload=value).stdout)

    def test_html_holds_opaque_pixels_while_reporting_external_exit(self):
        # Execute the actual generated script against only its DOM boundary.
        # This catches an opacity write, not merely a renamed state field.
        script = """
const vm = require('node:vm');
const m = require(process.argv[1]);
const b = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const html = m.htmlFor(m.validateBrief(b));
const nodes = {'.source': [{style:{}}], '.connector': [{style:{}}], '#hub': {style:{}}, '#stage': {style:{}}};
const context = {document: {querySelectorAll: s => nodes[s], querySelector: s => nodes[s]}};
vm.createContext(context);
vm.runInContext(html.match(/<script>([\\s\\S]*?)<\\/script>/)[1], context);
const result = [108, 114, 119, 120].map(f => ({state: context.seekFrame(f), alpha: Number(nodes['#stage'].style.opacity ?? 1)}));
process.stdout.write(JSON.stringify(result));
"""
        result = subprocess.run(
            ["node", "-e", script, str(RENDERER)], input=json.dumps(brief()),
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        items = json.loads(result.stdout)
        for item in items:
            self.assertEqual(item["alpha"], 1, item)
        for item in items:
            self.assertEqual(item["state"]["artifact_alpha"], 1)

    def test_strict_shape_and_relation_constraints_are_rejected(self):
        cases = []
        value = brief(2); value["canvas"]["duration_in_frames"] = 47; cases.append(value)
        value = brief(2); value["source_ids"] = ["s0", "s0"]; cases.append(value)
        value = brief(2); value["motion"]["family"] = "hierarchy"; cases.append(value)
        value = brief(2); value["motion"]["subjects"][0]["preserve"] = True; cases.append(value)
        value = brief(2); value["motion"]["actions"][0]["subject_ids"] = ["s0"]; cases.append(value)
        value = brief(2); value["hub_id"] = "s0"; cases.append(value)
        value = brief(2); value["motion"]["actions"][0]["depends_on"] = ["x"]; cases.append(value)
        value = brief(2); value["motion"]["actions"][1]["id"] = value["motion"]["actions"][0]["id"]; cases.append(value)
        value = brief(2); value["motion"]["actions"][2]["id"] = "x\n"; cases.append(value)
        value = brief(2); value["motion"]["actions"][2]["id"] = "x" * 81; cases.append(value)
        for invalid in cases:
            result = self.run_node("--validate", payload=invalid)
            self.assertNotEqual(result.returncode, 0)

    def test_frame_and_required_fields_are_strict(self):
        value = brief(4); value["motion"]["read_window"]["start_frame"] = 35; self.assertNotEqual(self.run_node("--validate", payload=value).returncode, 0)
        value = brief(2); value["title"] = "\n"; self.assertNotEqual(self.run_node("--validate", payload=value).returncode, 0)
        value = brief(2); value["extra"] = True; self.assertNotEqual(self.run_node("--validate", payload=value).returncode, 0)
        self.assertNotEqual(self.run_node("--state", "121", payload=brief(2)).returncode, 0)

    def test_external_exit_needs_at_least_two_encoded_frames(self):
        value = brief()
        value["motion"]["read_window"]["end_frame"] = 119
        value["motion"]["exit_window"]["start_frame"] = 119
        result = self.run_node("--validate", payload=value)
        self.assertNotEqual(result.returncode, 0)

    def test_visible_text_capacity_is_strict_unicode_and_source_text_is_not_displayed(self):
        for field, value in (("title", "字" * 13), ("hub", "字" * 5), ("source", "字" * 9)):
            invalid = brief(2)
            if field == "title": invalid["title"] = value
            elif field == "hub": invalid["motion"]["subjects"][-1]["label"] = value
            else: invalid["motion"]["subjects"][0]["label"] = value
            self.assertNotEqual(self.run_node("--validate", payload=invalid).returncode, 0)
        valid = brief(4)
        valid["motion"]["source_text"] = "</script>" + "字" * 190
        result = self.run_node("--validate", payload=valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        html = self.run_node("--html", payload=valid).stdout
        self.assertNotIn("</script><script>", html)

    def test_layout_connects_each_source_to_hub(self):
        checked = json.loads(self.run_node("--validate", payload=brief(4)).stdout)
        self.assertEqual(len(checked["layout"]["sources"]), 4)
        self.assertEqual(len(checked["layout"]["paths"]), len(checked["layout"]["sources"]))
        for source, path in zip(checked["layout"]["sources"], checked["layout"]["paths"]):
            self.assertEqual(source["right"], path["start"][0])
            self.assertEqual(checked["layout"]["hub"]["left"], path["end"][0])

    def test_vertical_layout_uses_body_and_keeps_nodes_in_safe_area(self):
        for count in (2, 3, 4):
            checked = json.loads(self.run_node("--validate", payload=brief(count)).stdout)
            nodes = checked["layout"]["sources"]
            if count == 4:
                self.assertLessEqual(nodes[0]["top"], 450)
                self.assertGreaterEqual(nodes[-1]["top"] + nodes[-1]["height"], 1500)
            for node in nodes + [checked["layout"]["hub"]]:
                self.assertGreaterEqual(node["left"], 64)
                self.assertLessEqual(node["left"] + node["width"], 1016)
                self.assertGreaterEqual(node["top"], 360)
                self.assertLessEqual(node["top"] + node["height"], 1700)
            for first, second in zip(nodes, nodes[1:]):
                self.assertGreaterEqual(second["top"] - first["top"] - first["height"], 48)
                self.assertLessEqual(second["top"] - first["top"] - first["height"], 300)
            hub = checked["layout"]["hub"]
            self.assertEqual((nodes[0]["centerY"] + nodes[-1]["centerY"]) / 2,
                             hub["top"] + hub["height"] / 2)

    def test_poster_typography_adapts_to_approved_text_length(self):
        value = brief(2)
        value["motion"]["subjects"][0]["label"] = "决策逻辑"
        value["motion"]["subjects"][1]["label"] = "一二三四五六七八"
        html = self.run_node("--html", payload=value).stdout
        self.assertIn("font-size:52px", html)
        self.assertIn("font-size:36px", html)
        self.assertIn('id="relation-poster-style"', html)
        self.assertIn("#stage h1", html)


if __name__ == "__main__":
    unittest.main()

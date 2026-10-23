"""Five semantic families must change scene geometry, not just planning labels."""

import json
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from edit.hd.tools.semantic_motion import build_motion_plan, PATTERNS


RENDERER = Path(__file__).resolve().parents[1] / "tools/semantic_state_renderer.cjs"


def brief(family="replacement", *, timing=(0, 20, 40, 60), layer_count=3):
    definitions = {
        "replacement": ([('machine', '机器', '蒸汽机', '电动机', False),
                         ('workflow', '工作流程', '布局不变', '布局不变', True)],
                        {"change_id": "machine", "context_ids": ["workflow"]},
                        [["machine", "workflow"], ["machine"], ["machine", "workflow"]]),
        "threshold": ([('ability', '能力', '尚未达标', '已经达标', False),
                       ('standard', '标准', '原有标准', '更高标准', False)],
                      {"capability_id": "ability", "threshold_id": "standard"},
                      [["ability", "standard"], ["ability"], ["standard"]]),
        "delay": ([('trigger', '技术诞生', '新技术出现', '新技术出现', True),
                   ('outcome', '生产力', '尚未释放', '逐步释放', False)],
                  {"trigger_id": "trigger", "outcome_id": "outcome"},
                  [["trigger", "outcome"], ["trigger", "outcome"], ["outcome"]]),
        "hierarchy": ([(f'l{i}', f'层级{i}', '尚未展开', f'细节{i}', False)
                       for i in range(layer_count)],
                      {"layer_ids": [f'l{i}' for i in range(layer_count)]},
                      [["l0"], [f'l{i}' for i in range(1, layer_count)],
                       [f'l{i}' for i in range(layer_count)]]),
        "feedback": ([('source', '决策', '原始判断', '修正判断', False),
                      ('result', '实践', '尚无反馈', '实际结果', False)],
                     {"source_id": "source", "result_id": "result"},
                     [["source"], ["result"], ["source"]]),
    }
    data, roles, targets = definitions[family]
    subjects = [dict(zip(("id", "label", "initial_state", "final_state", "preserve"), item))
                for item in data]
    actions = [
        {"id": f"phase{i}", "operation": op, "subject_ids": targets[i],
         "start_frame": timing[i], "end_frame": timing[i + 1],
         "depends_on": [] if i == 0 else [f"phase{i - 1}"]}
        for i, op in enumerate(PATTERNS[family])
    ]
    motion = {"version": 1, "content_item_id": "synthetic-item", "source_text": "维护测试原文",
              "family": family, "meaningful_change": "按原文关系显示主体变化",
              "subjects": subjects, "actions": actions, "duration_frames": 120,
              "read_window": {"start_frame": timing[-1], "end_frame": 108, "minimum_frames": 24},
              "exit_window": {"start_frame": 108, "end_frame": 120}}
    return {"schema_version": 1, "title": "语义动效测试", "roles": roles, "motion": motion,
            "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 120}}


class SemanticStateRendererTests(unittest.TestCase):
    def test_five_families_have_distinct_poster_structure(self):
        expected = {
            "replacement": {"replacement-stage", "preserved-context", "payoff"},
            "threshold": {"capability-track", "threshold-track", "payoff"},
            "delay": {"trigger-stage", "elapsed-stage", "outcome-stage", "payoff"},
            "hierarchy": {"layer-stack", "layer-connector", "payoff"},
            "feedback": {"forward-path", "return-path", "payoff"},
        }
        family_structures = {}
        for family, required_roles in expected.items():
            result = self.run_node("--svg", brief(family), 72)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = ET.fromstring(result.stdout)
            self.assertEqual(root.attrib.get("data-family"), family)
            self.assertEqual(root.attrib.get("data-visual-system"), "semantic-poster-v2")
            actual = {element.attrib["data-role"] for element in root.iter()
                      if "data-role" in element.attrib}
            self.assertTrue(required_roles <= actual, (family, required_roles - actual))
            family_structures[family] = frozenset(actual)
        self.assertEqual(len(set(family_structures.values())), len(expected))

    def test_stable_frame_has_no_empty_decorations_and_uses_real_content(self):
        forbidden = {"placeholder", "empty-circle", "floating-rule"}
        generic_copy = {"主题", "关键值", "结论", "内容"}
        for family in PATTERNS.keys() - {"relation"}:
            value = brief(family)
            result = self.run_node("--svg", value, 72)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = ET.fromstring(result.stdout)
            roles = [element.attrib["data-role"] for element in root.iter()
                     if "data-role" in element.attrib]
            self.assertTrue(forbidden.isdisjoint(roles), (family, roles))
            self.assertEqual(roles.count("content-unit"), len(value["motion"]["subjects"]))
            payoff = next(element for element in root.iter()
                          if element.attrib.get("data-role") == "payoff")
            payoff_text = "".join(payoff.itertext()).strip()
            self.assertTrue(payoff_text)
            self.assertFalse(generic_copy & set(payoff_text.split()), payoff_text)
            source_copy = {value["motion"]["meaningful_change"]}
            source_copy.update(subject["final_state"] for subject in value["motion"]["subjects"])
            self.assertTrue(any(copy in payoff_text or payoff_text in copy for copy in source_copy),
                            (family, payoff_text, source_copy))

    def test_dark_cards_keep_changed_copy_readable_and_threshold_track_is_balanced(self):
        for family in ("hierarchy", "feedback"):
            result = self.run_node("--svg", brief(family), 72)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = ET.fromstring(result.stdout)
            dark_groups = []
            for group in root.iter():
                if group.attrib.get("data-role") != "content-unit":
                    continue
                rects = [child for child in group if child.tag.endswith("rect")]
                if len(rects) > 1 and rects[1].attrib.get("fill") == "#111B3A":
                    dark_groups.append(group)
            self.assertTrue(dark_groups, family)
            for group in dark_groups:
                visible_changed = [element for element in group.iter()
                                   if element.tag.endswith("text")
                                   and element.attrib.get("opacity") == "1"
                                   and element.attrib.get("fill") == "#FFD44D"]
                self.assertTrue(visible_changed, (family, ET.tostring(group, encoding="unicode")))

        for frame in (20, 40, 50, 60, 72):
            result = self.run_node("--svg", brief("threshold"), frame)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = ET.fromstring(result.stdout)
            axis = next(element for element in root.iter()
                        if element.attrib.get("data-role") == "threshold-axis")
            rule = next(element for element in root.iter() if "data-rule" in element.attrib)
            rule_y = float(rule.attrib["d"].split()[2])
            self.assertGreaterEqual(rule_y, float(axis.attrib["data-axis-min-y"]))
            self.assertLessEqual(rule_y, float(axis.attrib["data-axis-max-y"]))

    def test_html_frame_bridge_escapes_inline_data(self):
        value = brief()
        value["motion"]["source_text"] = '</script><script>globalThis.injected=1</script>'
        result = self.run_node("--html", value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('<script>'), 1)
        self.assertEqual(result.stdout.count('</script>'), 1)
        self.assertNotIn('</script><script>globalThis.injected', result.stdout)
        self.assertIn('window.seekFrame', result.stdout)

    def run_node(self, mode, value, *args):
        self.assertTrue(RENDERER.is_file(), "five-family scene renderer is missing")
        return subprocess.run(["node", str(RENDERER), mode, *map(str, args)],
                              input=json.dumps(value), text=True, capture_output=True, timeout=10)

    def states(self, value, *frames):
        result = self.run_node("--states", value, *frames)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fixtures_match_existing_planner_and_renderer_does_not_mutate_brief(self):
        for family in PATTERNS.keys() - {"relation"}:
            value = brief(family)
            build_motion_plan(value["motion"], approved_items=[{
                "id": "synthetic-item", "source_text": "维护测试原文", "evidence_status": "supported"}])
            result = self.run_node("--validate", value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), value)

    def test_replacement_changes_machine_but_context_keeps_geometry_and_text(self):
        initial, middle, done, reading = self.states(brief(), 20, 30, 40, 72)
        self.assertEqual(initial["nodes"][0]["state_mix"], 0)
        self.assertEqual(middle["nodes"][0]["state_mix"], .5)
        self.assertEqual(done["nodes"][0]["state_mix"], 1)
        self.assertEqual(initial["nodes"][1], middle["nodes"][1])
        self.assertEqual(initial["nodes"][1], reading["nodes"][1])
        self.assertEqual(initial["nodes"][1]["initial_state"], "布局不变")

    def test_replacement_moves_the_object_out_then_in_not_only_its_wording(self):
        start, leaving, entering, done = self.states(brief(), 20, 25, 35, 40)
        self.assertLess(leaving["nodes"][0]["x"], start["nodes"][0]["x"])
        self.assertGreater(entering["nodes"][0]["x"], done["nodes"][0]["x"])
        self.assertLess(leaving["nodes"][0]["opacity"], 1)
        self.assertLess(entering["nodes"][0]["opacity"], 1)
        self.assertEqual(start["nodes"][1], done["nodes"][1])

    def test_threshold_crossing_precedes_rising_standard(self):
        start, crossing, crossed, rising, end = self.states(brief("threshold"), 20, 30, 40, 50, 60)
        self.assertGreater(start["bars"][0]["y"], start["rules"][0]["y"])
        self.assertLess(crossing["bars"][0]["y"], start["bars"][0]["y"])
        self.assertLess(crossed["bars"][0]["y"], crossed["rules"][0]["y"])
        self.assertEqual(start["rules"][0]["y"], crossed["rules"][0]["y"])
        self.assertLess(rising["rules"][0]["y"], crossed["rules"][0]["y"])
        self.assertLess(end["rules"][0]["y"], end["bars"][0]["y"])
        self.assertEqual(crossed["bars"][0], end["bars"][0])

    def test_delay_waits_before_showing_outcome(self):
        before, wait, ready, realizing, done = self.states(brief("delay"), 20, 30, 40, 50, 60)
        for item in (before, wait, ready):
            self.assertEqual(item["nodes"][1]["state_mix"], 0)
        self.assertEqual(wait["clock"]["progress"], .5)
        self.assertEqual(realizing["nodes"][1]["state_mix"], .5)
        self.assertEqual(done["nodes"][1]["state_mix"], 1)
        self.assertEqual(before["nodes"][0], done["nodes"][0])

    def test_hierarchy_reveals_layers_in_order_before_resolving(self):
        before, first, all_layers, done = self.states(brief("hierarchy"), 20, 25, 40, 60)
        self.assertEqual([n["opacity"] for n in before["nodes"]], [1, 0, 0])
        self.assertEqual([n["opacity"] for n in first["nodes"]], [1, .5, 0])
        self.assertEqual([n["opacity"] for n in all_layers["nodes"]], [1, 1, 1])
        self.assertEqual([n["state_mix"] for n in all_layers["nodes"]], [0, 0, 0])
        self.assertEqual([n["state_mix"] for n in done["nodes"]], [1, 1, 1])

    def test_feedback_result_then_return_then_source_update(self):
        before, output, returning, done = self.states(brief("feedback"), 20, 40, 50, 60)
        self.assertEqual(before["nodes"][1]["opacity"], 0)
        self.assertEqual(output["nodes"][1]["opacity"], 1)
        self.assertEqual(output["links"][1]["progress"], 0)
        self.assertEqual(output["nodes"][0]["state_mix"], 0)
        self.assertGreater(returning["links"][1]["progress"], 0)
        self.assertEqual(returning["nodes"][0]["state_mix"], 0)
        self.assertEqual(done["links"][1]["progress"], 1)
        self.assertEqual(done["nodes"][0]["state_mix"], 1)

    def test_connectors_touch_the_nodes_they_describe(self):
        delay = self.states(brief("delay"), 72)[0]
        clock, outcome = delay["clock"], delay["nodes"][1]
        self.assertEqual(delay["links"][0]["d"],
                         f'M {clock["x"]} {clock["y"] + clock["radius"]} L {clock["x"]} {outcome["y"]}')
        feedback = self.states(brief("feedback"), 72)[0]
        source, result = feedback["nodes"]
        center = source["x"] + source["width"] // 2
        self.assertEqual(feedback["links"][0]["d"],
                         f'M {center} {source["y"] + source["height"]} L {center} {result["y"]}')
        replacement = self.states(brief(), 72)[0]
        self.assertEqual(replacement["links"][0]["d"], 'M 100 590 H 76 V 905 H 100')

    def test_svg_connectors_use_the_visible_poster_geometry(self):
        expected = {
            "replacement": {"comparison": "M 540 728 V 890"},
            "delay": {"elapsed": "M 540 952 V 1120"},
            "hierarchy": {"layer-1": "M 540 634 V 694", "layer-2": "M 540 908 V 968"},
            "feedback": {
                "produce": "M 540 666 V 1110",
                "return": "M 962 1228 C 1032 1228,1032 548,962 548",
            },
        }
        for family, paths in expected.items():
            result = self.run_node("--svg", brief(family), 72)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = ET.fromstring(result.stdout)
            actual = {element.attrib["data-link"]: element.attrib["d"]
                      for element in root.iter() if "data-link" in element.attrib}
            self.assertEqual(actual, paths, family)

    def test_every_family_holds_reading_pixels_and_leaves_exit_to_compositor(self):
        for family in PATTERNS.keys() - {"relation"}:
            with self.subTest(family=family):
                value = brief(family)
                frames = (72, 107, 108, 114, 119, 120)
                states = self.states(value, *frames)
                for item in states:
                    self.assertEqual(item["artifact_alpha"], 1)
                self.assertAlmostEqual(states[3]["compositor_alpha"], 5 / 11)
                self.assertEqual(states[-2]["compositor_alpha"], 0)
                images = []
                for frame in frames:
                    rendered = self.run_node("--svg", value, frame)
                    self.assertEqual(rendered.returncode, 0, rendered.stderr)
                    root = ET.fromstring(rendered.stdout)
                    ids = {element.attrib["data-subject"] for element in root.iter()
                           if "data-subject" in element.attrib}
                    self.assertEqual(ids, {s["id"] for s in value["motion"]["subjects"]})
                    images.append(rendered.stdout)
                self.assertEqual(len(set(images)), 1)

    def test_timing_is_consumed_not_fixed_percentages(self):
        normal = self.states(brief(), 30)[0]
        retimed = self.states(brief(timing=(4, 30, 50, 70)), 30)[0]
        self.assertEqual(normal["nodes"][0]["state_mix"], .5)
        self.assertEqual(retimed["nodes"][0]["state_mix"], 0)

    def test_all_node_geometry_stays_clear_of_title_and_bottom_avatar(self):
        values = [brief(family) for family in PATTERNS.keys() - {"relation"}]
        values.extend(brief("hierarchy", layer_count=count) for count in (2, 4))
        many = brief()
        for suffix in (2, 3):
            context_id = f"workflow{suffix}"
            many["motion"]["subjects"].append({**many["motion"]["subjects"][1], "id": context_id})
            many["roles"]["context_ids"].append(context_id)
            for index in (0, 2):
                many["motion"]["actions"][index]["subject_ids"].append(context_id)
        values.append(many)
        for value in values:
            for state in self.states(value, *range(0, 121, 5)):
                for node in state["nodes"]:
                    with self.subTest(family=state["family"], frame=state["frame"], node=node["id"]):
                        self.assertGreaterEqual(node["y"], 350)
                        self.assertLessEqual(node["y"] + node["height"], 1600)
                        self.assertGreaterEqual(node["x"], 64)
                        self.assertLessEqual(node["x"] + node["width"], 1016)
                        self.assertFalse(node["x"] < 1020 and node["x"] + node["width"] > 796
                                         and node["y"] < 1674 and node["y"] + node["height"] > 1450,
                                         "node intersects bottom-right avatar reservation")

    def test_state_text_never_crossfades_two_different_words_on_top_of_each_other(self):
        result = self.run_node("--svg", brief(), 25)
        self.assertEqual(result.returncode, 0, result.stderr)
        root = ET.fromstring(result.stdout)
        machine = next(e for e in root.iter() if e.attrib.get("data-subject") == "machine")
        states = list(machine.findall('{http://www.w3.org/2000/svg}text'))[1:]
        self.assertEqual(sum(float(t.attrib.get("opacity", 1)) > 0 for t in states), 1)

    def test_renderer_does_not_mutate_even_frozen_input(self):
        script = """
const m=require(process.argv[1]), input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const before=JSON.stringify(input);
function freeze(x){if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}}
freeze(input);
const checked=m.validateBrief(input);freeze(checked);
for(const f of [0,20,30,40,60,119]) {m.frameState(checked,f);m.svgFor(checked,f);}
if(JSON.stringify(input)!==before||JSON.stringify(checked)!==before)throw Error('mutated');
process.stdout.write('unchanged');
"""
        result = subprocess.run(["node", "-e", script, str(RENDERER)], input=json.dumps(brief()),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "unchanged")

    def test_invalid_frames_do_not_clamp_or_wrap(self):
        for frame in (-1, 121, "NaN", "true", .5, "", " "):
            self.assertNotEqual(self.run_node("--states", brief(), frame).returncode, 0)

    def test_cli_rejects_oversized_json_before_parsing(self):
        result = subprocess.run(["node", str(RENDERER), "--validate"],
                                input=' ' * (256 * 1024) + json.dumps(brief()),
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("brief exceeds 262144 bytes", result.stderr)

    def test_strict_roles_targets_capacity_and_phase_validation(self):
        cases = []
        for mutation in (
            lambda b: b.update(extra=True),
            lambda b: b["canvas"].update(width=1920),
            lambda b: b["roles"].update(change_id="workflow"),
            lambda b: b["roles"].update(context_ids=["workflow", "workflow"]),
            lambda b: b["motion"]["actions"][1].update(subject_ids=["machine", "workflow"]),
            lambda b: b["motion"]["actions"][1].update(depends_on=[]),
            lambda b: b["motion"]["actions"][1].update(start_frame=19),
            lambda b: b["motion"]["actions"][1].update(end_frame=True),
            lambda b: b["motion"]["subjects"][1].update(preserve=False),
            lambda b: b["motion"]["subjects"][1].update(final_state="被改变"),
            lambda b: b["motion"]["subjects"][0].update(label="字" * 13),
            lambda b: b["motion"]["subjects"][0].update(final_state="字" * 17),
            lambda b: b["motion"]["read_window"].update(start_frame=59),
            lambda b: b["motion"]["read_window"].update(minimum_frames=80),
            lambda b: b["motion"]["exit_window"].update(start_frame=119),
        ):
            value = brief(); mutation(value); cases.append(value)
        cases.extend([brief("hierarchy", layer_count=1), brief("hierarchy", layer_count=5)])
        for value in cases:
            with self.subTest(value=value):
                self.assertNotEqual(self.run_node("--validate", value).returncode, 0)

    def test_svg_uses_real_labels_escapes_markup_and_has_no_external_assets(self):
        value = brief()
        value["title"] = '标题<&"测试'
        value["motion"]["subjects"][0]["label"] = '<script>'
        value["motion"]["source_text"] = '</script>NOT_VISIBLE'
        result = self.run_node("--svg", value, 72)
        self.assertEqual(result.returncode, 0, result.stderr)
        root = ET.fromstring(result.stdout)
        self.assertEqual(root.attrib["viewBox"], "0 0 1080 1920")
        text = ''.join(root.itertext())
        self.assertIn('<script>', text)
        self.assertIn('电动机', text)
        self.assertNotIn('NOT_VISIBLE', text)
        self.assertNotIn('<script>', result.stdout)
        self.assertNotRegex(result.stdout, r'href=|<image|<foreignObject')


if __name__ == "__main__":
    unittest.main()

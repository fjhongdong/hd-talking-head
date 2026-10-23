"""Focused contracts for orchestrating Paper, without generating paid imagery."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skill-development/hd-talking-head/scripts"))
import paper_collage_adapter as paper
import dependency_preflight as preflight
from render_paper_collage import validate_brief
from edit.hd.tests.test_broll_component_executor import _code_component, _recipe
from edit.hd.tools import visual_canary


def brief_fixture():
    return {"schema_version": 1,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-001", "start": .5, "end": 3.625},
            "template_request": {"semantic_family": "threshold", "information_units": 2,
                                 "numeric_values": [], "numeric_scale": "not_applicable"},
            "manifest": {"width": 1080, "height": 1920, "fps": 24, "duration": 3.125, "crf": 18,
                         "steps": 84, "finalHold": .625, "fadeDuration": 1 / 3,
                         "background": "field", "finalFrame": "final",
                         "layers": [{"image": "hand", "from": "bottom", "x": 0, "y": 0,
                                     "startAt": -4.9, "travel": 7}]},
            "assets": [{"media_ref": ref, "job_path": f"images/{ref}.png", "sha256": "b" * 64,
                        "geometry": "full_canvas",
                        "provenance": {"kind": "ai_generated", "tool": "image_gen", "record_path": "prompts.json",
                                       "record_sha256": "c" * 64}} for ref in ("field", "final", "hand")]}


class PaperContracts(unittest.TestCase):
    def test_selected_dependency_has_a_real_binding_probe(self):
        manifest = preflight._load_manifest(paper.SKILL / "references/dependency-manifest.json")
        item = next(item for item in manifest["dependencies"] if item["id"] == "paper-collage-adapter")
        binding = {"component_kind": "code_generated", "dependency_id": paper.DEPENDENCY_ID,
                   "entrypoint": paper.ENTRY, "producer_version": paper.VERSION,
                   "executor": "reference_adapter", "primary_renderer": "PaperCollage"}
        self.assertEqual(preflight._selected_recipe_binding(item, [binding]), binding)
        result = preflight._check_binding_probe(item, binding, project_root=ROOT,
            reference_root=ROOT / "参考项目/B-roll开源方案", dependency_root=paper.SKILL)
        self.assertEqual(result["status"], "bound")

    def test_negative_preroll_and_separate_image_provenance(self):
        brief = brief_fixture()
        self.assertEqual(validate_brief(json.dumps(brief).encode()), brief)
        brief["assets"][2]["geometry"] = "native_cutout"
        self.assertEqual(validate_brief(json.dumps(brief).encode()), brief)
        for mutate in (lambda b: b["assets"].pop(),
                       lambda b: b["assets"][0].update(job_path="../other.png"),
                       lambda b: b["assets"][0].update(geometry="native_cutout"),
                       lambda b: b["assets"][0]["provenance"].update(kind="code_generated"),
                       lambda b: b["manifest"].update(duration=3.12),
                       lambda b: b["manifest"]["layers"][0].update(travel=0)):
            changed = copy.deepcopy(brief)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate_brief(json.dumps(changed).encode())

    def test_current_plan_clock_and_all_media_are_bound(self):
        brief = brief_fixture()
        payload = json.dumps(brief).encode()
        adapter = paper.create_adapter(
            upstream_root=ROOT / "skill-development/vendor/paper-collage-ad-codex",
            python_executable=sys.executable, node_executable=shutil.which("node"),
            ffmpeg_executable=shutil.which("ffmpeg"), ffprobe_executable=shutil.which("ffprobe"),
            brief_loader=lambda *_: json.dumps(brief).encode())
        component = _code_component(payload)
        component.update(paper.create_binding(adapter, payload, paper.SKILL / paper.ENTRY))
        component["artifact_contract"]["alpha"] = False
        component["render_window"]["end_frame"] = 75
        recipe = _recipe([component])
        segment = {"segment_id": "seg-001", "start": .5, "end": 3.625, "shot_recipe": recipe}
        with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": [segment]}), \
             patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": "a" * 64}):
            self.assertEqual(adapter.brief_loader(None, recipe, component), payload)
            media = adapter.media_loader(None, recipe, component, payload)
            self.assertEqual({m.job_path for m in media}, {"images/field.png", "images/final.png", "images/hand.png", "prompts.json"})
            for key, changed in (("aroll_sha256", "d" * 64), ("start", .6), ("end", 4), ("segment_id", "seg-002")):
                original = brief["source_binding"][key]
                brief["source_binding"][key] = changed
                with self.subTest(key=key), self.assertRaises(ValueError):
                    adapter.brief_loader(None, recipe, component)
                brief["source_binding"][key] = original


if __name__ == "__main__":
    unittest.main()

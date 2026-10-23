"""Focused Whiteboard binding checks; real rendering uses the maintenance fixture."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skill-development/hd-talking-head/scripts"))
import dependency_preflight as preflight
import whiteboard_adapter as whiteboard
import render_whiteboard as wrapper
from edit.hd.tests.test_broll_component_executor import _code_component, _recipe
from edit.hd.tools import visual_canary


def brief_fixture():
    return {"schema_version": 1,
            "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-001", "start": 3.5, "end": 6.625},
            "template_request": {"semantic_family": "process-relations", "information_units": 4,
                                 "numeric_values": [], "numeric_scale": "not_applicable"},
            "render": {"width": 1080, "height": 1920, "fps": 24, "duration": 3.125,
                       "line_thickness": 7, "tail_hold": 1, "draw_blocks": 4},
            "assets": [{"media_ref": ref, "job_path": f"assets/{ref}.{suffix}", "sha256": "b" * 64}
                       for ref, suffix in (("svg", "svg"), ("source", "png"))],
            "provenance": {"record_path": "provenance.json", "record_sha256": "c" * 64}}


def make_adapter(loader):
    vendor = ROOT / "skill-development/vendor"
    engine = vendor / "whiteboard-video-engine"
    return whiteboard.create_adapter(vendor / "codex-whiteboard-video-skill", engine, sys.executable,
                                     engine / ".venv/bin/python", shutil.which("ffmpeg"), shutil.which("ffprobe"), loader)


class WhiteboardContracts(unittest.TestCase):
    def test_selected_dependency_has_actual_runtime_binding(self):
        manifest = preflight._load_manifest(whiteboard.SKILL / "references/dependency-manifest.json")
        item = next(item for item in manifest["dependencies"] if item["id"] == "whiteboard-video-adapter")
        binding = {"component_kind": "code_generated", "dependency_id": whiteboard.DEPENDENCY_ID,
                   "entrypoint": whiteboard.ENTRY, "producer_version": whiteboard.VERSION,
                   "executor": "reference_adapter", "primary_renderer": "Whiteboard"}
        self.assertEqual(preflight._selected_recipe_binding(item, [binding]), binding)
        result = preflight._check_binding_probe(item, binding, project_root=ROOT,
            reference_root=ROOT / "参考项目/B-roll开源方案", dependency_root=whiteboard.SKILL)
        self.assertEqual(result["status"], "bound", result)

    def test_only_bounded_silent_svg_settings_are_accepted(self):
        brief = brief_fixture()
        self.assertEqual(wrapper.validate_brief(json.dumps(brief).encode()), brief)
        for mutate in (lambda b: b["assets"].pop(),
                       lambda b: b["assets"][0].update(job_path="../source.svg"),
                       lambda b: b["render"].update(duration=3.12),
                       lambda b: b["render"].update(tail_hold=3.125),
                       lambda b: b["render"].update(argv=["--tts-provider", "edge"])):
            changed = copy.deepcopy(brief)
            mutate(changed)
            with self.assertRaises(ValueError):
                wrapper.validate_brief(json.dumps(changed).encode())

    def test_source_clock_and_pair_remain_bound(self):
        brief = brief_fixture()
        payload = json.dumps(brief).encode()
        adapter = make_adapter(lambda *_: json.dumps(brief).encode())
        component = _code_component(payload, dependency_id=whiteboard.DEPENDENCY_ID)
        component.update(whiteboard.create_binding(adapter, payload, whiteboard.SKILL / whiteboard.ENTRY))
        component["artifact_contract"]["alpha"] = False
        component["render_window"]["end_frame"] = 75
        recipe = _recipe([component])
        segment = {"segment_id": "seg-001", "start": 3.5, "end": 6.625, "shot_recipe": recipe}
        with patch.object(visual_canary, "load_approved_visual_plan", return_value={"segments": [segment]}), \
             patch.object(visual_canary, "approved_aroll_record", return_value={"sha256": "a" * 64}):
            self.assertEqual(adapter.brief_loader(None, recipe, component), payload)
            media = adapter.media_loader(None, recipe, component, payload)
            self.assertEqual({m.media_ref for m in media}, {"svg", "source", "provenance"})
            for key, value in (("aroll_sha256", "d" * 64), ("start", 3.4), ("end", 6.5)):
                original = brief["source_binding"][key]
                brief["source_binding"][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    adapter.brief_loader(None, recipe, component)
                brief["source_binding"][key] = original

    def test_changed_upstream_is_rejected_without_rendering(self):
        engine = ROOT / "skill-development/vendor/whiteboard-video-engine"
        with tempfile.TemporaryDirectory(prefix="whiteboard-test-") as directory:
            upstream = Path(directory) / "whiteboard_cli.py"
            upstream.write_text("raise RuntimeError('must not execute')\n")
            with self.assertRaisesRegex(ValueError, "upstream"):
                wrapper.check_runtime(upstream, engine, engine / ".venv/bin/python")


if __name__ == "__main__":
    unittest.main()

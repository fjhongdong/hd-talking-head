"""Offline brief-contract regression for the motion graphics adapter."""
import importlib.util
import copy
import json
import sys
import unittest
import tempfile
import hashlib
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import _env  # noqa: F401

SKILL = _env.SKILL
sys.path.insert(0, str(SKILL / "scripts"))

spec = importlib.util.spec_from_file_location(
    "motion_graphics_adapter", SKILL / "scripts/motion_graphics_adapter.py")
mga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mga)


def brief(family="lower_third"):
    data = {
        "lower_third": {"name": "李明", "role": "首席科学家", "org": "智源研究院"},
        "callout_pin": {"target_desc": "图表第三列的数据", "label": "关键增量", "direction": "up"},
        "logo_sting": {"mark_text": "AI课", "headline": "看懂AI不用慌", "cta": "关注更新"},
    }[family]
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-mg-1",
                           "start": 0.0, "end": 4.0},
        "template_request": {"semantic_family": family,
                             "information_units": 3, "numeric_values": [],
                             "numeric_scale": "not_applicable"},
        "composition": {"id": "mg-lower-1", "width": 1080, "height": 1920,
                        "fps": 24, "frames": 96, "alpha": True},
        "entry": {"job_path": "motion-graphics/lower-third-1.html", "sha256": "b" * 64},
        "assets": [],
        "data": data,
    }


class MotionGraphicsBriefTests(unittest.TestCase):
    def check(self, mutate, pattern):
        payload = brief()
        mutate(payload)
        with self.assertRaisesRegex(ValueError, pattern):
            mga.validate_brief(json.dumps(payload))

    def test_valid_lower_third(self):
        checked = mga.validate_brief(json.dumps(brief("lower_third")))
        self.assertEqual(checked["data"]["name"], "李明")

    def test_valid_callout_pin(self):
        checked = mga.validate_brief(json.dumps(brief("callout_pin")))
        self.assertEqual(checked["data"]["direction"], "up")

    def test_valid_logo_sting(self):
        checked = mga.validate_brief(json.dumps(brief("logo_sting")))
        self.assertEqual(checked["data"]["mark_text"], "AI课")

    def test_rejects_unknown_family(self):
        self.check(lambda b: b["template_request"].__setitem__("semantic_family", "keyword"),
                   "family")

    def test_rejects_bad_clock(self):
        self.check(lambda b: b["composition"].__setitem__("frames", 50),
                   "composition clock")

    def test_rejects_alpha_false(self):
        self.check(lambda b: b["composition"].__setitem__("alpha", False),
                   "composition clock")

    def test_rejects_absolute_entry_path(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "/tmp/graphic.html"),
                   "Job-relative HTML")

    def test_rejects_non_html_entry(self):
        self.check(lambda b: b["entry"].__setitem__("job_path", "motion-graphics/graphic.js"),
                   "Job-relative HTML")

    def test_rejects_nonempty_assets(self):
        self.check(lambda b: b.__setitem__("assets", [{"media_ref": "x"}]),
                   "assets must be empty")

    def test_rejects_overlong_name(self):
        self.check(lambda b: b["data"].__setitem__("name", "超过八个字符的名字一定不行"),
                   "name")

    def test_rejects_bad_direction(self):
        payload = brief("callout_pin")
        payload["data"]["direction"] = "diagonal"
        with self.assertRaisesRegex(ValueError, "direction"):
            mga.validate_brief(json.dumps(payload))

    def test_rejects_wrong_data_slots(self):
        self.check(lambda b: b["data"].__setitem__("extra", "x"), "data slots")

    def test_runtime_probe(self):
        if not _env.EDIT_HD_AVAILABLE:
            self.skipTest("runtime unavailable")
        rt = mga.check_runtime(_env.PROJECT)
        self.assertIn("identity", rt)

    def test_selected_binding_passes_real_preflight_probe(self):
        import dependency_preflight as preflight
        manifest = preflight._load_manifest(SKILL / "references/dependency-manifest.json")
        item = next(row for row in manifest["dependencies"] if row["id"] == mga.DEPENDENCY_ID)
        selected = {"dependency_id": mga.DEPENDENCY_ID, "entrypoint": mga.ENTRY,
            "producer_version": mga.VERSION, "executor": "reference_adapter",
            "primary_renderer": "HyperFrames"}
        result = preflight._check_binding_probe(item, selected,
            project_root=_env.PROJECT, reference_root=_env.PROJECT / "参考项目/B-roll开源方案",
            dependency_root=SKILL)
        self.assertEqual(result["status"], "bound", result)

    def test_default_loader_finds_frozen_brief_without_fixed_filename(self):
        import run_stage
        from edit.hd.tools import visual_canary
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "native-inputs").mkdir()
            payload = json.dumps(brief("callout_pin")).encode()
            (root / "native-inputs/renamed-brief.json").write_bytes(payload)
            component = {"kind": "code_generated", "dependency_id": mga.DEPENDENCY_ID,
                "entrypoint": mga.ENTRY, "template_id": "motion-graphics-native/callout_pin",
                "brief_sha256": hashlib.sha256(payload).hexdigest()}
            plan = {"segments": [{"shot_recipe": {"components": [component]}}]}
            # Expose the real default loader without starting any renderer.
            module = SimpleNamespace(create_adapter=lambda *args: args[-1])
            job = SimpleNamespace(job_dir=root)
            with patch.object(visual_canary, "load_approved_visual_plan", return_value=plan), \
                    patch.object(run_stage, "_module", return_value=module):
                loader = run_stage.native_component_adapters(_env.PROJECT, job)["code_generated"][mga.DEPENDENCY_ID]
                self.assertEqual(loader(job, {}, component), payload)
                with self.assertRaisesRegex(ValueError, "Frozen native brief is missing"):
                    loader(job, {}, {**component, "brief_sha256": "0" * 64})

    def test_connected_callout_uses_node_and_frozen_entry(self):
        payload = json.dumps(brief("callout_pin")).encode()
        adapter = mga.create_adapter(_env.PROJECT, sys.executable, lambda *_: payload)
        self.assertTrue(adapter.launcher.name.startswith("node"))
        self.assertTrue(adapter.self_contained_wrapper)
        self.assertIn("{media_manifest_fd}", adapter.argv_template)
        runtime = mga.check_runtime(_env.PROJECT)
        for flag, key in (("--ffmpeg", "ffmpeg"), ("--ffprobe", "ffprobe")):
            self.assertEqual(adapter.argv_template[adapter.argv_template.index(flag) + 1], runtime[key])
            self.assertTrue(Path(runtime[key]).is_absolute())
            self.assertTrue(Path(runtime[key]).is_file())
        media = adapter.media_loader(None, None, None, payload)
        self.assertEqual([(r.media_ref, r.job_path, r.sha256) for r in media],
                         [("native-entry", brief("callout_pin")["entry"]["job_path"], "b" * 64)])

    def test_callout_binding_complies_with_real_recipe_contract(self):
        from edit.hd.tools.visual_strategy import validate_shot_recipe_v2
        payload = json.dumps(brief("callout_pin")).encode()
        adapter = mga.create_adapter(_env.PROJECT, sys.executable, lambda *_: payload)
        binding = mga.create_binding(adapter, payload, Path(__file__))
        component = {"component_id": "visual", "kind": "code_generated",
            "semantic_role": "explanation", "layer_role": "annotation",
            "executor": "reference_adapter", "media_type": "animation",
            "render_window": {"start_frame": 0, "end_frame": 96,
                "z_index": 10, "layout_slot": "annotation", "opacity": 1,
                "safe_zone": {"top": 64, "bottom": 320, "left": 40, "right": 40}},
            "artifact_contract": {"width": 1080, "height": 1920, "fps": 24, "alpha": True},
            **binding}
        checked = validate_shot_recipe_v2({"schema_version": 2, "segment_id": "seg-mg-1",
            "strategy_revision": 1, "mode": "none",
            "composition": {"family": "aroll_with_overlay", "presenter_mode": "full_frame",
                "reading_order": ["visual"], "component_dependencies": []},
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "components": [component], "final_compositor": "ffmpeg"})
        self.assertEqual(checked["components"][0]["template_id"],
                         "motion-graphics-native/callout_pin")
        from edit.hd.tools.motion_capabilities import _brief_overlay_route
        self.assertEqual(_brief_overlay_route(json.loads(payload)), "callout-pin")
        for family in ("lower_third", "logo_sting"):
            self.assertIsNone(_brief_overlay_route(brief(family)))

    def test_only_callout_is_connected_to_production(self):
        import run_stage
        from edit.hd.tools.motion_capabilities import overlay_candidates
        adapter = mga.create_adapter(_env.PROJECT, sys.executable, lambda *_: b"")
        for family in ("lower_third", "logo_sting"):
            with self.subTest(family=family), self.assertRaisesRegex(ValueError, "only for callout_pin"):
                mga.create_binding(adapter, json.dumps(brief(family)).encode(), Path(__file__))
        binding = {"dependency_id": "motion-graphics-native", "entrypoint": mga.ENTRY,
                   "template_id": "motion-graphics-native/callout_pin"}
        run_stage._check_default_binding(binding)
        with self.assertRaisesRegex(ValueError, "Only the connected"):
            run_stage._check_default_binding({**binding, "template_id": "motion-graphics-native/logo_sting"})
        candidates = [r["candidate_id"] for r in overlay_candidates(_env.PROJECT)
                      if r["dependency_id"] == "motion-graphics-native"]
        self.assertEqual(candidates, ["overlay:callout-pin"])

    def test_callout_compiles_through_public_router(self):
        from edit.hd.tests.test_broll_capability_router import (
            _load_router, _visual_intent, _strategy_component, _visual_strategy,
            avatar_fixture)
        payload = json.dumps(brief("callout_pin")).encode()
        adapter = mga.create_adapter(_env.PROJECT, sys.executable, lambda *_: payload)
        binding = mga.create_binding(adapter, payload, Path(__file__))
        strategy = _visual_strategy([_strategy_component(
            "visual", "code_generated", layout_slot="annotation")], segment_id="seg-mg-1")
        strategy["mode"] = "none"
        strategy["composition"] = {"family": "aroll_with_overlay",
            "presenter_mode": "full_frame", "reading_order": ["visual"],
            "component_dependencies": []}
        context = {"intent": _visual_intent("seg-mg-1"),
            "bindings": {"visual": binding}, "candidate_snapshots": {},
            "segment_frames": 96}
        router = _load_router()
        recipe = router.compile_strategy(strategy, context)
        self.assertEqual(recipe["components"][0]["executor"], "reference_adapter")
        self.assertTrue(recipe["components"][0]["artifact_contract"]["alpha"])
        for field, value in (("template_id", "motion-graphics-native/logo_sting"),
                             ("template_id", "motion-graphics-native/lower_third"),
                             ("primary_renderer", "HTMLCanvas"),
                             ("adaptation_level", "tokens_only"),
                             ("source_entrypoint", "scripts/openfilm_motion_adapter.py")):
            bad = copy.deepcopy(context)
            bad["bindings"]["visual"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                router.compile_strategy(strategy, bad)
        broll = _visual_strategy([_strategy_component(
            "visual", "code_generated", layout_slot="full_frame")], segment_id="seg-mg-1")
        broll["composition"]["avatar"] = avatar_fixture(frames=96)
        with self.assertRaisesRegex(ValueError, "A-roll annotations"):
            router.compile_strategy(broll, context)


if __name__ == "__main__":
    unittest.main()

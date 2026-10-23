import importlib.util
import json
import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skill-development/hd-talking-head/scripts/openfilm_motion_adapter.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openfilm_motion_adapter_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def brief(module):
    return {
        "schema_version": 1,
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-001", "start": 0.0, "end": 2.0},
        "template_request": {"semantic_family": "cause_transition", "information_units": 2, "numeric_values": [], "numeric_scale": "not_applicable"},
        "composition": {"width": 1080, "height": 1920, "fps": 24, "frames": 48, "alpha": False},
        "entry": {"media_ref": "entry", "job_path": "assets/index.html", "scene_path": "index.html", "sha256": "b" * 64},
        "assets": [],
        "upstream": {"package_version": module.PACKAGE_VERSION, "skill_sha256": "c" * 64, "manual_sha256": "d" * 64},
        "creative_handoff": {"transcript": "先整理再交给工具", "semantic_goal": "整理流程", "required_change": "从混乱变清晰", "subject": "费用记录", "visual_pattern": "主体推动整理", "style_reason": "突出主体动作", "beats": [{"start_frame": 0, "end_frame": 48, "spoken_anchor": "整理", "before": "记录混乱", "action": "主体归类并推进", "after": "形成清晰结构"}], "forbidden_outcomes": []},
    }


class OpenFilmMotionAdapterTest(unittest.TestCase):
    def test_frozen_gsap_library_and_real_external_references(self):
        module = load_module()
        library = ROOT / "参考项目/B-roll开源方案/hyperframes/skills/talking-head-recut/assets/vendor/gsap.min.js"
        value = brief(module)
        value["assets"] = [{"media_ref": "gsap", "job_path": "assets/gsap.min.js",
                            "scene_path": "vendor/gsap.min.js", "sha256": module.sha(library)}]
        entry = ('<script src="vendor/gsap.min.js"></script><script>'
                 'const scene=gsap.timeline({paused:true});'
                 'window.film={width:1080,height:1920,duration:2,frame(t){scene.seek(t);}};'
                 '</script>')
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory)
            (scene / "vendor").mkdir()
            shutil.copyfile(library, scene / "vendor/gsap.min.js")
            (scene / "index.html").write_text(entry)
            module._check_scene(scene, value)
            for external in ('<script src="https://example.invalid/lib.js"></script>',
                             '<style>@import "https://example.invalid/font.css";</style>',
                             '<img src="//example.invalid/image.png">'):
                (scene / "index.html").write_text(entry + external)
                with self.subTest(reference=external), self.assertRaises(ValueError):
                    module._check_scene(scene, value)

    def test_brief_and_native_resource_contract(self):
        module = load_module()
        value = brief(module)
        self.assertEqual(module.validate_brief(json.dumps(value))["composition"]["fps"], 24)
        for mutation in ("alpha", "clock", "action", "destination"):
            bad = copy.deepcopy(value)
            if mutation == "alpha": bad["composition"]["alpha"] = True
            if mutation == "clock": bad["creative_handoff"]["beats"][0]["end_frame"] = 49
            if mutation == "action": bad["creative_handoff"]["beats"][0]["action"] = ""
            if mutation == "destination":
                bad["assets"] = [{**bad["entry"], "media_ref": "duplicate"}]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                module.validate_brief(json.dumps(bad))
        # Read the approved native page, never alter it or render another video.
        source = ROOT / "skill-development/test-output/openfilm-evidence-20261018/evidence-v2.html"
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory)
            shutil.copyfile(source, scene / "index.html")
            module._check_scene(scene, value)
            with self.assertRaisesRegex(ValueError, "different native instructions"):
                module._check_upstream(value, module.check_runtime(ROOT))

    def test_factory_and_opaque_recipe_compile(self):
        from edit.hd.tests.test_broll_capability_router import (
            _load_router, _visual_intent, _visual_strategy, _strategy_component, avatar_fixture)
        from edit.hd.tools import visual_plan, broll_component_executor
        module = load_module()
        runtime = module.check_runtime(ROOT)
        adapter = module.create_adapter(ROOT, sys.executable, lambda *_: b"")
        value = brief(module)
        value["upstream"] = {"package_version": module.PACKAGE_VERSION,
                             "skill_sha256": module.sha(Path(runtime["skill"])),
                             "manual_sha256": module.sha(Path(runtime["manual"]))}
        sample = ROOT / "skill-development/test-output/openfilm-evidence-20261018/openfilm-visual-v2.mp4"
        payload = json.dumps(value, ensure_ascii=False).encode()
        binding = module.create_binding(adapter, payload, sample)
        self.assertEqual(broll_component_executor._DEPENDENCY_CONTRACTS[module.DEPENDENCY_ID],
                         ("reference_adapter", "OpenFilm"))
        router = _load_router()
        component = _strategy_component("scene", "code_generated", layout_slot="full_frame")
        strategy = _visual_strategy([component])
        strategy["composition"]["avatar"] = avatar_fixture(frames=48)
        context = {"intent": _visual_intent(), "bindings": {"scene": binding},
                   "candidate_snapshots": {}, "segment_frames": 48}
        visual_plan._prevalidate_draft_bindings(strategy, context["bindings"], 1, 48)
        recipe = router.compile_strategy(strategy, context)
        self.assertEqual(recipe["components"][0]["artifact_contract"],
                         {"width":1080, "height":1920, "fps":24, "alpha":False})
        self.assertEqual(binding["invocation_record"]["status"], "planned")
        binding["primary_renderer"] = "Remotion"
        with self.assertRaises(router.RouterError):
            router.compile_strategy(strategy, context)


if __name__ == "__main__":
    unittest.main()


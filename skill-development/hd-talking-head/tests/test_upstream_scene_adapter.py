"""Focused regression checks for scene input and semantic-first routing."""
import copy
import json
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL.parent.parent))
import upstream_scene_adapter as scene
import broll_capability_router as router
try:
    import edit.hd  # noqa: F401
except ImportError:
    edit_hd_available = False
else:
    edit_hd_available = True


def brief():
    return {"schema_version": 1, "dependency_id": "onetake",
        "source_binding": {"aroll_sha256": "a" * 64, "segment_id": "seg-1", "start": 0, "end": 6},
        "template_request": {"semantic_family": "process", "information_units": 3, "numeric_values": [], "numeric_scale": "not_applicable"},
        "composition": {"id": "task", "width": 1080, "height": 1920, "fps": 24, "frames": 144},
        "files": [{"media_ref": "entry", "job_path": "scene/index.html", "scene_path": "index.html", "sha256": "b" * 64},
                  {"media_ref": "workflow", "job_path": "scene/workflow.json", "scene_path": "workflow.json", "sha256": "c" * 64}],
        "workflow_media_ref": "workflow"}

def lemo_brief(slug="blueprint"):
    b = brief(); b.update(dependency_id="lemo-opuscar", style_slug=slug,
        creative_handoff={"transcript":"我不会", "semantic_goal":"开始", "required_change":"清晰",
            "subject":"诗诗", "visual_pattern":"纸张", "design_plan":{"composition":"居中","typography":"大字","finish":"暖色","focus":"双手"},
            "beats":[{"time":0, "action":"出现"}], "forbidden_outcomes":["乱码"]})
    b["files"].append({"media_ref":"treatment", "job_path":"scene/TREATMENT.md",
        "scene_path":"TREATMENT.md", "sha256":"d"*64})
    return b


@unittest.skipUnless(edit_hd_available, "edit.hd runtime is unavailable; run from the project checkout")
class UpstreamSceneTests(unittest.TestCase):
    def test_lemo_workflow_rejects_changed_instructions_and_treatment(self):
        b = lemo_brief("swiss-motion")
        root = SKILL.parents[1] / "skill-development/vendor/lemo-opuscar"
        instructions = ["plugin/skills/lemo-opuscar/SKILL.md", "AGENTS.md", "DIRECTOR.md",
                        "TECHNIQUE.md", "styles/swiss-motion/STYLE.md"]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "index.html").write_text("<script>const seg = 1;</script>")
            (work / "TREATMENT.md").write_text("本期主题和动作。")
            b["files"][-1]["sha256"] = scene.sha(work / "TREATMENT.md")
            workflow = {"dependency_id":"lemo-opuscar", "upstream_commit":scene.SOURCES['lemo-opuscar'][0],
                "style_slug":"swiss-motion", "template_id":"lemo-opuscar/swiss-motion",
                "instructions":instructions, "instruction_sha256":{p:scene.sha(root/p) for p in instructions},
                "treatment_media_ref":"treatment", "design_plan":b["creative_handoff"]["design_plan"],
                "concept":"本期场景", "beat_sheet":["本期动作"], "qa":["待实际检查"],
                "upstream_features":[{"path":"core/lib.js", "symbol":"seg", "usage":"动作进度"}]}
            def write():
                (work / "workflow.json").write_text(json.dumps(workflow))
            write()
            scene.validate_workflow(b,work,root)
            saved=workflow['instruction_sha256'][instructions[0]]
            workflow['instruction_sha256'][instructions[0]]='0'*64
            write()
            with self.assertRaisesRegex(ValueError,"instruction source changed"):
                scene.validate_workflow(b,work,root)
            workflow['instruction_sha256'][instructions[0]]=saved
            write()
            (work / "TREATMENT.md").write_text("替换后的方案。")
            with self.assertRaisesRegex(ValueError,"treatment file is missing or changed"):
                scene.validate_workflow(b,work,root)

    def test_frozen_entrypoint_starts_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-", "--skill-root", str(SKILL), "--help"],
                input=(SKILL / scene.ENTRY).read_bytes(), cwd=directory, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"--media-manifest", result.stdout)

    def test_selected_lemo_style_matches_native_input_and_router(self):
        from edit.hd.tools import motion_capabilities
        rows = {r["template_id"]: r for r in motion_capabilities.load_catalog(SKILL.parents[1])
                if r.get("dependency_id") == "lemo-opuscar"}
        b = lemo_brief("blueprint")
        self.assertEqual(motion_capabilities._native_input_check(
            SKILL.parents[1], rows["lemo-opuscar/blueprint"], b)["status"], "pass")
        self.assertEqual(motion_capabilities._native_input_check(
            SKILL.parents[1], rows["lemo-opuscar/swiss-motion"], b)["status"], "fail")
        adapter = SimpleNamespace(dependency_id="lemo-opuscar", launcher="python",
            entrypoint_sha256=scene.sha(scene.SKILL / scene.ENTRY),
            renderer_version=scene.SOURCES["lemo-opuscar"][0])
        binding = scene.create_binding(adapter, json.dumps(b).encode(), __file__)
        router.validate_template_binding(binding)
        changed = copy.deepcopy(binding)
        changed["template_id"] = "lemo-opuscar/swiss-motion"
        with self.assertRaises(router.RouterError):
            router.validate_template_binding(changed)

    def test_lemo_catalog_and_style_identity(self):
        catalog = scene.lemo_styles(SKILL.parents[1])
        self.assertEqual(len(catalog), 59)
        for slug in catalog:
            b = lemo_brief(slug); data = json.dumps(b)
            self.assertEqual(scene.validate_brief(data)["style_slug"], slug)
            adapter = SimpleNamespace(dependency_id="lemo-opuscar", entrypoint_sha256=scene.sha(scene.SKILL / scene.ENTRY),
                renderer_version=scene.SOURCES["lemo-opuscar"][0], launcher="node")
            binding = scene.create_binding(adapter, data.encode(), __file__)
            self.assertEqual(binding["template_id"], "lemo-opuscar/" + slug)
            router.validate_template_binding(binding)
        with self.assertRaises(ValueError): scene.validate_brief(json.dumps(lemo_brief("missing-style")))

    def test_lemo_handoff_required_and_onetake_is_unchanged(self):
        b = lemo_brief(); b.pop("creative_handoff")
        with self.assertRaises(ValueError): scene.validate_brief(json.dumps(b))
        b = lemo_brief(); b["creative_handoff"]["design_plan"].pop("focus")
        with self.assertRaises(ValueError): scene.validate_brief(json.dumps(b))
        b = lemo_brief(); b["files"].pop()
        with self.assertRaisesRegex(ValueError, "TREATMENT.md"):
            scene.validate_brief(json.dumps(b))
        self.assertNotIn("style_slug", scene.create_binding(SimpleNamespace(dependency_id="onetake", entrypoint_sha256=scene.sha(scene.SKILL / scene.ENTRY), renderer_version=scene.SOURCES["onetake"][0], launcher="python"), json.dumps(brief()).encode(), __file__))
    def test_scene_clock_and_frozen_paths_are_required(self):
        self.assertEqual(scene.validate_brief(json.dumps(brief())), brief())
        for mutate in (lambda b: b["composition"].update(frames=143),
                       lambda b: b["files"][0].update(scene_path="../index.html"),
                       lambda b: b["files"][1].update(scene_path="_frames/asset.png"),
                       lambda b: b.update(workflow_media_ref="missing")):
            b = brief()
            mutate(b)
            with self.assertRaises(ValueError):
                scene.validate_brief(json.dumps(b))

    def test_higher_semantic_match_precedes_template_qualification(self):
        fixed = {"template_origin": "verified_third_party", "template_id": "fixed",
            "template_version": "1", "verification_id": "a" * 64, "adaptation_level": "content_reflow",
            "source_entrypoint": "scripts/render_doudou.mjs", "source_sha256": "b" * 64, "sample_sha256": "c" * 64,
            "semantic_families": ["process"], "capacity": {"min_units": 1, "max_units": 3},
            "semantic_match_score": .6, "quality_score": .95, "reuse_gap": 12}
        upstream = copy.deepcopy(fixed)
        upstream.update(template_id="upstream-scene", template_origin="custom_fallback", adaptation_level="structural", semantic_match_score=.95)
        ranked = router.rank_code_templates([fixed, upstream], semantic_family="process", information_units=3)
        self.assertEqual(ranked[0]["template_id"], "upstream-scene")
        upstream["semantic_match_score"] = .6
        ranked = router.rank_code_templates([fixed, upstream], semantic_family="process", information_units=3)
        self.assertEqual(ranked[0]["template_id"], "fixed")
        upstream["quality_score"] = .98
        ranked = router.rank_code_templates([fixed, upstream], semantic_family="process", information_units=3)
        self.assertEqual(ranked[0]["template_id"], "upstream-scene")

    def test_new_dependencies_use_native_opaque_execution(self):
        for dependency_id in scene.SOURCES:
            self.assertEqual(router._PRIMARY_RENDERER[dependency_id], "HTMLCanvas")
            self.assertEqual(router._executor("code_generated", {"dependency_id": dependency_id}), "reference_adapter")

    def test_qualified_talkcraft_identity_is_catalog_bound(self):
        from edit.hd.tools.talkcraft_matcher import load_card_catalog

        card = load_card_catalog()[0]
        production = card["production"]
        candidate = {
            "template_origin": "custom_fallback",
            "template_id": f"hd-talking-head/talkcraft/{card['card_id']}",
            "template_version": production["adapter_version"],
            "verification_id": production["qualification_id"],
            "adaptation_level": "structural",
            "source_entrypoint": production["derived_entrypoint"],
            "source_sha256": production["implementation_sha256"],
            "sample_sha256": card["sample_sha256"],
            "semantic_families": ["process"],
            "capacity": {"min_units": 1, "max_units": 8},
            "semantic_match_score": .9, "quality_score": .9, "reuse_gap": 1,
        }
        self.assertEqual(router.rank_code_templates([candidate], semantic_family="process", information_units=1)[0]["template_id"], candidate["template_id"])
        for field in ("template_id", "source_sha256", "sample_sha256"):
            tampered = copy.deepcopy(candidate)
            tampered[field] = "0" * 64 if field.endswith("sha256") else "hd-talking-head/talkcraft/not-registered"
            with self.assertRaises(router.RouterError):
                router.rank_code_templates([tampered], semantic_family="process", information_units=1)
        bypass = copy.deepcopy(candidate)
        bypass["template_id"] = "hd-talking-head/talkcraft/not-registered"
        bypass["source_entrypoint"] = "scripts/render_doudou.mjs"
        with self.assertRaises(router.RouterError):
            router.rank_code_templates([bypass], semantic_family="process", information_units=1)


if __name__ == "__main__":
    unittest.main()

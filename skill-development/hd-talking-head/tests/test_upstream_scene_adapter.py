"""Focused regression checks for scene input and semantic-first routing."""
import copy
import json
from pathlib import Path
import sys
import unittest

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


@unittest.skipUnless(edit_hd_available, "edit.hd runtime is unavailable; run from the project checkout")
class UpstreamSceneTests(unittest.TestCase):
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

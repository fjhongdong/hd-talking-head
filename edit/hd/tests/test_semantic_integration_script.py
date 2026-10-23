"""Qualification fixtures for the five new SemanticState template families."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "skill-development/hd-talking-head/tests"
    / "render_semantic_state_integration.py"
)
RENDERER = Path(__file__).resolve().parents[1] / "tools/semantic_state_renderer.cjs"


def load_module():
    spec = importlib.util.spec_from_file_location("semantic_state_integration", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("SemanticState integration script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SemanticStateIntegrationScriptTests(unittest.TestCase):
    def test_two_distinct_valid_briefs_exist_for_every_family(self):
        module = load_module()
        self.assertEqual(
            module.FAMILIES,
            ("replacement", "threshold", "delay", "hierarchy", "feedback"),
        )
        for family in module.FAMILIES:
            with self.subTest(family=family):
                first = module.make_brief(family, 1)
                second = module.make_brief(family, 2)
                self.assertNotEqual(first["motion"]["source_text"], second["motion"]["source_text"])
                self.assertEqual(first["motion"]["family"], family)
                self.assertEqual(second["motion"]["family"], family)
                for brief in (first, second):
                    result = subprocess.run(
                        ["/usr/local/bin/node", str(RENDERER), "--validate"],
                        input=json.dumps(brief, ensure_ascii=False),
                        text=True,
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), brief)

    def test_qualification_briefs_exercise_required_structural_variants(self):
        module = load_module()

        replacement = [module.make_brief("replacement", variant) for variant in (1, 2)]
        self.assertEqual(
            [len(brief["roles"]["context_ids"]) for brief in replacement],
            [1, 3],
        )
        hierarchy = [module.make_brief("hierarchy", variant) for variant in (1, 2)]
        self.assertEqual(
            [len(brief["roles"]["layer_ids"]) for brief in hierarchy],
            [2, 4],
        )

        for family in module.FAMILIES:
            with self.subTest(family=family):
                first = module.make_brief(family, 1)
                second = module.make_brief(family, 2)
                self.assertNotEqual(first["title"], second["title"])
                self.assertNotEqual(
                    first["motion"]["source_text"], second["motion"]["source_text"]
                )
                first_subjects = [
                    (item["label"], item["initial_state"], item["final_state"])
                    for item in first["motion"]["subjects"]
                ]
                second_subjects = [
                    (item["label"], item["initial_state"], item["final_state"])
                    for item in second["motion"]["subjects"]
                ]
                self.assertNotEqual(first_subjects, second_subjects)

                for brief in (first, second):
                    source_text = brief["motion"]["source_text"]
                    for subject in brief["motion"]["subjects"]:
                        self.assertIn(subject["label"], source_text)

    def test_action_evidence_frames_follow_each_declared_phase(self):
        module = load_module()
        for family in module.FAMILIES:
            brief = module.make_brief(family, 1)
            evidence = module.action_evidence_frames(brief)
            self.assertEqual(len(evidence), 3)
            self.assertEqual([item[0] for item in evidence], [
                action["operation"] for action in brief["motion"]["actions"]
            ])
            self.assertEqual([item[1] for item in evidence], [19, 39, 59])

    def test_qualification_maps_motion_families_to_content_analysis_types(self):
        module = load_module()
        from edit.hd.tools.content_analysis import ALLOWED_SEMANTIC_TYPES

        self.assertEqual(set(module.CONTENT_SEMANTIC_TYPES), set(module.FAMILIES))
        self.assertTrue(set(module.CONTENT_SEMANTIC_TYPES.values()) <= ALLOWED_SEMANTIC_TYPES)
        self.assertEqual(module.CONTENT_SEMANTIC_TYPES["replacement"], "contrast")
        self.assertEqual(module.CONTENT_SEMANTIC_TYPES["threshold"], "contrast")
        self.assertEqual(module.CONTENT_SEMANTIC_TYPES["delay"], "process")
        self.assertEqual(module.CONTENT_SEMANTIC_TYPES["hierarchy"], "process")
        self.assertEqual(module.CONTENT_SEMANTIC_TYPES["feedback"], "process")

    def test_human_review_binds_seed_manifest_brief_sample_and_family(self):
        module = load_module()
        base = module.SKILL / "assets/verified-templates"
        with tempfile.TemporaryDirectory(dir=base) as directory:
            root = Path(directory)
            families = []
            for family in module.FAMILIES:
                folder = root / family
                folder.mkdir()
                brief = folder / "brief.json"
                sample = folder / "sample.mp4"
                value = module.make_brief(family, 1)
                brief.write_text(json.dumps(value), encoding="utf-8")
                sample.write_bytes(("sample-" + family).encode())
                frame_evidence = []
                frame_folder = folder / "frames"
                frame_folder.mkdir()
                for role, frame in (("entry", 10), ("stable", 72), ("exit", 119)):
                    path = frame_folder / f"{role}.png"
                    path.write_bytes(b"\x89PNG\r\n\x1a\n" + role.encode())
                    frame_evidence.append({
                        "role": role,
                        "timestamp_sec": frame / 24,
                        **module._proof(path),
                    })
                action_frames = []
                action_folder = folder / "action-frames"
                action_folder.mkdir()
                for role, frame in module.action_evidence_frames(value):
                    path = action_folder / f"{role}.png"
                    path.write_bytes(b"\x89PNG\r\n\x1a\n" + role.encode())
                    action_frames.append({
                        "role": role,
                        "timestamp_sec": frame / 24,
                        **module._proof(path),
                    })
                families.append({
                    "family": family,
                    "template_id": module.TEMPLATES[family],
                    "brief": module._proof(brief),
                    "sample": module._proof(sample),
                    "frame_evidence": frame_evidence,
                    "action_frames": action_frames,
                })
            manifest = root / "pending-review.json"
            module._write_json(manifest, {
                "status": "pending_visual_review",
                "human_approval_claimed": False,
                "source": module._proof(module.SKILL / module.ENTRY),
                "families": families,
            })
            lineage = module.load_seed_lineage(root)
            item = lineage["families"]["replacement"]
            value = {
                "schema_version": 1,
                "status": "approved",
                "reviewer_type": "human",
                "reviewer": "User",
                "reviewed_at": "2026-09-06T12:00:00+08:00",
                "approval_reference": "conversation-review-1",
                "family": "replacement",
                "template_id": module.TEMPLATES["replacement"],
                "seed_manifest_sha256": lineage["manifest_sha256"],
                "brief_sha256": item["brief"]["sha256"],
                "sample_sha256": item["sample"]["sha256"],
                "source_sha256": lineage["source_sha256"],
                "visual_qa": {"status": "approved"},
                "action_sequence_qa": {"status": "approved"},
            }
            checked = module.validate_review(
                value, family="replacement",
                seed_manifest_sha256=lineage["manifest_sha256"],
                brief_sha256=item["brief"]["sha256"],
                sample_sha256=item["sample"]["sha256"],
                source_sha256=lineage["source_sha256"],
            )
            self.assertEqual(checked, value)

            with mock.patch.object(module, "_read_snapshot", return_value=b"changed-source"):
                with self.assertRaisesRegex(ValueError, "renderer changed after review"):
                    module.assert_reviewed_source(lineage)

            candidate = module._candidate(
                "replacement", root / "replacement/sample.mp4", value,
                source_sha256=lineage["source_sha256"],
                frame_evidence=item["frame_evidence"],
                action_frames=item["action_frames"],
            )
            self.assertEqual(candidate["source_sha256"], lineage["source_sha256"])
            self.assertEqual(
                candidate["source_files"][0]["sha256"], lineage["source_sha256"],
            )
            self.assertEqual(
                {frame["role"] for frame in candidate["visual_qa"]["frame_evidence"]},
                {"entry", "stable", "exit"},
            )
            self.assertEqual(
                [event["event"] for event in candidate["action_sequence_qa"]["events"]],
                list(module.PATTERNS["replacement"]),
            )
            self.assertTrue(all(candidate["visual_qa"]["checks"].values()))

            proof = {"path": "assets/verified-templates/example", "sha256": "a" * 64}
            cases = [
                {
                    "brief": proof,
                    "recipe": proof,
                    "receipt": proof,
                    "sample": proof,
                    "frame_evidence": item["frame_evidence"],
                    "action_frames": item["action_frames"],
                }
                for _ in range(2)
            ]
            reviewed = module._reviewed_candidate(
                candidate,
                source_registry=proof,
                cases=cases,
                reviewed_at="2026-09-07",
            )
            self.assertNotIn("execution_qa", candidate)
            self.assertEqual(reviewed["execution_qa"]["status"], "reviewed")
            self.assertEqual(
                set(reviewed["execution_qa"]["cases"][0]),
                {"brief", "recipe", "receipt", "sample", "frame_evidence"},
            )
            self.assertNotEqual(reviewed["verification_id"], candidate["verification_id"])
            for key, replacement in (
                ("status", "pending"),
                ("reviewer_type", "agent"),
                ("family", "threshold"),
                ("brief_sha256", "0" * 64),
                ("sample_sha256", "0" * 64),
                ("seed_manifest_sha256", "0" * 64),
            ):
                with self.subTest(key=key):
                    changed = {**value, key: replacement}
                    with self.assertRaises(ValueError):
                        module.validate_review(
                            changed, family="replacement",
                            seed_manifest_sha256=lineage["manifest_sha256"],
                            brief_sha256=item["brief"]["sha256"],
                            sample_sha256=item["sample"]["sha256"],
                            source_sha256=lineage["source_sha256"],
                        )
            with self.assertRaises(ValueError):
                module.validate_review(
                    {**value, "extra": True}, family="replacement",
                    seed_manifest_sha256=lineage["manifest_sha256"],
                    brief_sha256=item["brief"]["sha256"],
                    sample_sha256=item["sample"]["sha256"],
                    source_sha256=lineage["source_sha256"],
                )

            manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_value["source"]["sha256"] = "0" * 64
            module._write_json(manifest, manifest_value)
            with self.assertRaises(ValueError):
                module.load_seed_lineage(root)

            manifest_value["source"] = module._proof(module.SKILL / module.ENTRY)
            module._write_json(manifest, manifest_value)
            (root / "replacement/sample.mp4").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                module.load_seed_lineage(root)

    def test_review_reader_is_bounded_strict_and_snapshot_based(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.json"
            review.write_text('{"status":"approved","status":"pending"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate keys"):
                module.load_review(review)

            review.write_text('{"score":NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                module.load_review(review)

            review.write_bytes(b"{" + b" " * (module.REVIEW_MAX_BYTES + 1) + b"}")
            with self.assertRaises(ValueError):
                module.load_review(review)

    def test_outputs_are_confined_to_verified_template_assets(self):
        module = load_module()
        allowed = module.SKILL / "assets/verified-templates/semantic-candidate"
        self.assertEqual(module._qualified_output(allowed), allowed)
        with self.assertRaises(ValueError):
            module._qualified_output(Path("/tmp/semantic-candidate"))


if __name__ == "__main__":
    unittest.main()

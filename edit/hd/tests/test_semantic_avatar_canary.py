"""Contract tests for the SemanticState avatar-composite canary."""

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "skill-development/hd-talking-head/tests"
    / "render_semantic_state_avatar_canary.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("semantic_avatar_canary", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("SemanticState avatar canary script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SemanticAvatarCanaryTests(unittest.TestCase):
    def qualification_fixture(self, module, root):
        qualification = root / "assets/verified-templates/qualification"
        report_families = []
        for family in module.FAMILIES:
            case = qualification / family / "case-2"
            case.mkdir(parents=True)
            for name in ("brief.json", "recipe.json", "execution.json"):
                (case / name).write_text("{}", encoding="utf-8")
            (case / "sample.mp4").write_bytes(("sample-" + family).encode())
            case_record = {
                key: {
                    "path": (case / name).relative_to(root).as_posix(),
                    "sha256": module.sha256(case / name),
                }
                for key, name in (
                    ("brief", "brief.json"),
                    ("recipe", "recipe.json"),
                    ("receipt", "execution.json"),
                    ("sample", "sample.mp4"),
                )
            }
            source_registry = qualification / family / "qualification/source-registry.json"
            source_registry.parent.mkdir()
            source_registry.write_text("{}", encoding="utf-8")
            registry = qualification / family / "reviewed-registry.json"
            registry_value = {
                "schema_version": 1,
                "templates": [{
                    "template_id": f"hd-talking-head/semantic-state-{family}",
                    "semantic_families": [family],
                    "visual_qa": {"status": "approved"},
                    "action_sequence_qa": {"status": "approved"},
                    "execution_qa": {
                        "status": "reviewed",
                        "source_registry": {
                            "path": source_registry.relative_to(root).as_posix(),
                            "sha256": module.sha256(source_registry),
                        },
                        "cases": [copy.deepcopy(case_record), copy.deepcopy(case_record)],
                    },
                }],
            }
            registry.write_text(json.dumps(registry_value), encoding="utf-8")
            report_families.append({
                "family": family,
                "template_id": f"hd-talking-head/semantic-state-{family}",
                "case_count": 2,
                "action_frames_verified": 6,
                "reviewed_registry": {
                    "path": registry.relative_to(root).as_posix(),
                    "sha256": module.sha256(registry),
                },
            })
        report = {
            "status": "reviewed",
            "human_approval_claimed": False,
            "families": report_families,
        }
        (qualification / "qualification-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return qualification

    def test_selects_reviewed_case_two_once_in_fixed_family_order(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualification = self.qualification_fixture(module, root)

            selected, evidence = module.select_reviewed_cases(root, qualification)

        self.assertEqual([item.family for item in selected], list(module.FAMILIES))
        self.assertTrue(all(item.case_id == "case-2" for item in selected))
        self.assertEqual(evidence["status"], "reviewed")

    def test_reviewed_case_hash_change_is_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualification = self.qualification_fixture(module, root)
            (qualification / "replacement/case-2/brief.json").write_text(
                "changed", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                module.select_reviewed_cases(root, qualification)

    def test_reviewed_case_is_frozen_before_later_path_replacement(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualification = self.qualification_fixture(module, root)
            selected, _ = module.select_reviewed_cases(root, qualification)
            item = selected[0]
            old_sample = item.sample_bytes
            (qualification / "replacement/case-2/recipe.json").write_text(
                '{"changed": true}', encoding="utf-8"
            )
            (qualification / "replacement/case-2/sample.mp4").write_bytes(b"changed")

            self.assertEqual(item.recipe, {})
            self.assertEqual(item.sample_bytes, old_sample)
            self.assertNotEqual(
                module.sha256(qualification / "replacement/case-2/sample.mp4"),
                item.case_evidence["sample"]["sha256"],
            )

    def test_avatar_is_added_without_mutating_formal_recipe(self):
        module = load_module()
        recipe = {
            "components": [{"component_id": "semantic-state-replacement"}],
            "composition": {
                "family": "single_full_frame",
                "presenter_mode": "bottom_window",
                "reading_order": ["semantic-state-replacement"],
                "component_dependencies": [],
            },
        }
        avatar = {"profile": {"source_sha256": "a" * 64}}
        original = copy.deepcopy(recipe)

        composed = module.with_avatar(recipe, avatar)

        self.assertEqual(recipe, original)
        self.assertEqual(composed["composition"]["avatar"], avatar)
        self.assertEqual(composed["components"], recipe["components"])

    def test_source_binding_must_match_actual_aroll(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"real-source")
            review = {
                "avatar": {
                    "profile": {"source_sha256": "0" * 64},
                }
            }
            with self.assertRaisesRegex(ValueError, "source SHA-256"):
                module.load_bound_avatar(review, source)

    def test_external_aroll_and_avatar_review_are_frozen_before_path_replacement(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            review = root / "review.json"
            source.write_bytes(b"first-source")
            review.write_text('{"avatar": "first"}', encoding="utf-8")

            source_bytes, review_bytes = module.freeze_external_inputs(source, review)
            source.write_bytes(b"second-source")
            review.write_text('{"avatar": "second"}', encoding="utf-8")

            self.assertEqual(source_bytes, b"first-source")
            self.assertEqual(json.loads(review_bytes)["avatar"], "first")

    def test_artifact_payload_rejects_non_video_or_wrong_frame_count(self):
        module = load_module()
        valid = {
            "artifact": {
                "status": "success",
                "artifact_media_type": "video",
                "media_probe": {
                    "width": 1080,
                    "height": 1920,
                    "fps": 24,
                    "frame_count": 120,
                },
            }
        }
        self.assertEqual(module.checked_artifact_payload(valid)["status"], "success")
        invalid = json.loads(json.dumps(valid))
        invalid["artifact"]["media_probe"]["frame_count"] = 119
        with self.assertRaisesRegex(ValueError, "120 frames"):
            module.checked_artifact_payload(invalid)

    def solid(self, path, color):
        Image.new("RGB", (108, 192), color).save(path)

    def test_pixel_qa_detects_missing_avatar_payoff_drift_and_exit_residue(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            poster = root / "poster.png"
            stable = root / "stable.png"
            source = root / "source.png"
            last = root / "last.png"
            self.solid(poster, "white")
            self.solid(source, "black")
            avatar = (78, 145, 102, 169)

            # A visible avatar changes only its ROI; everything else stays exact.
            with Image.open(poster) as image:
                visible = image.copy()
            for x in range(avatar[0], avatar[2]):
                for y in range(avatar[1], avatar[3]):
                    visible.putpixel((x, y), (0, 0, 0))
            visible.save(stable)
            self.solid(last, "black")
            metrics = module.assert_pixel_qa(
                poster, stable, source, last, avatar,
                stable_threshold=1, presence_threshold=10, exit_threshold=1,
            )
            self.assertEqual(metrics["status"], "verified")

            self.solid(stable, "white")
            with self.assertRaisesRegex(AssertionError, "avatar is absent"):
                module.assert_pixel_qa(
                    poster, stable, source, last, avatar,
                    stable_threshold=1, presence_threshold=10, exit_threshold=1,
                )

            visible.save(stable)
            with Image.open(stable) as image:
                payoff_drift = image.copy()
            for x in range(5, 35):
                for y in range(150, 165):
                    payoff_drift.putpixel((x, y), (255, 0, 0))
            payoff_drift.save(stable)
            with self.assertRaisesRegex(AssertionError, "payoff"):
                module.assert_pixel_qa(
                    poster, stable, source, last, avatar,
                    stable_threshold=1, presence_threshold=10, exit_threshold=1,
                )

            visible.save(stable)
            with Image.open(source) as image:
                residue = image.copy()
            for x in range(avatar[0], avatar[2]):
                for y in range(avatar[1], avatar[3]):
                    residue.putpixel((x, y), (255, 255, 255))
            residue.save(last)
            with self.assertRaisesRegex(AssertionError, "exit avatar ROI"):
                module.assert_pixel_qa(
                    poster, stable, source, last, avatar,
                    stable_threshold=1, presence_threshold=10, exit_threshold=1,
                )

    def test_owned_staging_cleans_failure_and_preserves_existing_target(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "canary"
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with module.owned_staging(target) as staging:
                    (staging / "partial.txt").write_text("partial")
                    raise RuntimeError("boom")
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

            target.mkdir()
            (target / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(ValueError, "must be new"):
                with module.owned_staging(target):
                    pass
            self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_montage_command_keeps_quote_path_as_one_argv_item(self):
        module = load_module()
        clips = [Path("/tmp/canary's output") / f"{family}.mp4" for family in module.FAMILIES]
        output = Path("/tmp/canary's output/review.mp4")
        argv = module.montage_command(Path("/opt/ffmpeg"), clips, output)
        for clip in clips:
            self.assertIn(str(clip), argv)
            self.assertEqual(argv.count(str(clip)), 1)
        self.assertEqual(argv[-1], str(output))

    def test_human_approval_rejects_minimal_receipt_without_qualification_proofs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canary = root / "assets/canary"
            canary.mkdir(parents=True)
            montage = canary / "semantic-state-5family-avatar-canary.mp4"
            contact = canary / "contact-sheet.png"
            montage.write_bytes(b"montage")
            contact.write_bytes(b"contact")
            receipt = canary / "canary-receipt.json"
            receipt.write_text(json.dumps({
                "status": "machine_verified_pending_human_review",
                "human_approval_claimed": False,
                "cases": [
                    {
                        "family": family,
                        "template_id": f"hd-talking-head/semantic-state-{family}",
                    }
                    for family in module.FAMILIES
                ],
                "montage": {"path": montage.name, "sha256": module.sha256(montage)},
                "contact_sheet": {"path": contact.name, "sha256": module.sha256(contact)},
            }), encoding="utf-8")
            review = canary / "review.json"
            review.write_text(json.dumps({
                "schema_version": 1,
                "status": "approved",
                "human_approval_claimed": True,
                "scope": "five-family SemanticState avatar-composite canary",
                "reviewer": "User",
                "reviewed_at": "2026-09-07T06:20:55+08:00",
                "approval_reference": "thread-test-user-confirmed-avatar-canary",
                "families": list(module.FAMILIES),
                "template_ids": [
                    f"hd-talking-head/semantic-state-{family}"
                    for family in module.FAMILIES
                ],
                "canary_receipt": {
                    "path": receipt.relative_to(root).as_posix(),
                    "sha256": module.sha256(receipt),
                },
                "montage": {
                    "path": montage.relative_to(root).as_posix(),
                    "sha256": module.sha256(montage),
                },
                "contact_sheet": {
                    "path": contact.relative_to(root).as_posix(),
                    "sha256": module.sha256(contact),
                },
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "canary receipt"):
                module.validate_human_approval(root, review)

    def test_committed_human_approval_has_complete_bound_machine_evidence(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        review = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored/review.json"
        )

        report = module.validate_human_approval(root, review)

        self.assertEqual(report["status"], "approved")
        self.assertEqual(report["families"], list(module.FAMILIES))

    def test_machine_evidence_rejects_pixel_qa_claim_without_verified_status(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        receipt_path = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored/canary-receipt.json"
        )
        receipt = module.read_json(receipt_path)
        receipt["cases"][0]["pixel_qa"]["status"] = "pending"

        with self.assertRaisesRegex(ValueError, "replacement pixel QA"):
            module.validate_canary_receipt(root, receipt_path, receipt)

    def test_bound_snapshot_rejects_internal_symbolic_link(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual.bin"
            alias = root / "alias.bin"
            actual.write_bytes(b"evidence")
            alias.symlink_to(actual.name)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                module.verified_bound_snapshot(
                    root,
                    {"path": alias.name, "sha256": module.sha256(actual)},
                    label="linked evidence",
                )

    def test_bound_snapshot_rejects_symbolic_link_escape(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            root = outer / "skill"
            root.mkdir()
            external = outer / "external.bin"
            alias = root / "alias.bin"
            external.write_bytes(b"external")
            alias.symlink_to(external)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                module.verified_bound_snapshot(
                    root,
                    {"path": alias.name, "sha256": module.sha256(external)},
                    label="escaping evidence",
                )

    def test_machine_evidence_reprobes_self_claimed_composite_media(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        source = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored"
        )
        with tempfile.TemporaryDirectory() as directory:
            canary = Path(directory) / "canary"
            shutil.copytree(source, canary)
            receipt_path = canary / "canary-receipt.json"
            receipt = module.read_json(receipt_path)
            composite = canary / "replacement/composite.mp4"
            composite.write_bytes(b"not-a-video")
            receipt["cases"][0]["composite"]["sha256"] = module.sha256(composite)
            receipt["cases"][0]["composite"]["bytes"] = composite.stat().st_size

            with self.assertRaisesRegex((ValueError, RuntimeError), "media probe"):
                module.validate_canary_receipt(root, receipt_path, receipt)

    def test_machine_evidence_recomputes_pixel_qa_metrics(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        receipt_path = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored/canary-receipt.json"
        )
        receipt = module.read_json(receipt_path)
        receipt["cases"][0]["pixel_qa"]["stable_payoff_mae"] += 0.5

        with self.assertRaisesRegex(ValueError, "differs from recomputation"):
            module.validate_canary_receipt(root, receipt_path, receipt)

    def test_machine_evidence_rejects_relaxed_pixel_qa_thresholds(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        receipt_path = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored/canary-receipt.json"
        )
        receipt = module.read_json(receipt_path)
        pixel = receipt["cases"][0]["pixel_qa"]
        pixel["stable_threshold"] = 1_000_000
        pixel["presence_threshold"] = 0.000001
        pixel["exit_threshold"] = 1_000_000

        with self.assertRaisesRegex(ValueError, "replacement pixel QA"):
            module.validate_canary_receipt(root, receipt_path, receipt)

    def test_machine_evidence_derives_pixel_references_from_bound_videos(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        source = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored"
        )
        with tempfile.TemporaryDirectory() as directory:
            canary = Path(directory) / "canary"
            shutil.copytree(source, canary)
            receipt_path = canary / "canary-receipt.json"
            receipt = module.read_json(receipt_path)
            for family in module.FAMILIES:
                (canary / family / "frames/original-stable-072.png").write_bytes(
                    b"untrusted cached frame"
                )
                (canary / family / "frames/source-last-119.png").write_bytes(
                    b"untrusted cached frame"
                )

            montage, _, contact, _ = module.validate_canary_receipt(
                root, receipt_path, receipt
            )

            self.assertEqual(
                montage,
                (canary / "semantic-state-5family-avatar-canary.mp4").resolve(),
            )
            self.assertEqual(contact, (canary / "contact-sheet.png").resolve())

    def test_montage_sequence_rejects_reordered_family_fingerprints(self):
        module = load_module()
        root = Path(module.__file__).resolve().parents[1]
        canary = (
            root
            / "assets/verified-templates/semantic-state-avatar-canary-20260918-restored"
        )
        stable_frames = [
            canary / family / "frames/stable-072.png"
            for family in reversed(module.FAMILIES)
        ]
        ffmpeg = module.validation_tool("HD_FFMPEG", "ffmpeg")

        with self.assertRaisesRegex(ValueError, "segment 1"):
            module.verify_montage_sequence(
                ffmpeg,
                canary / "semantic-state-5family-avatar-canary.mp4",
                stable_frames,
            )

    def test_human_approval_rejects_changed_canary_media(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canary = root / "canary"
            canary.mkdir()
            montage = canary / "montage.mp4"
            contact = canary / "contact.png"
            montage.write_bytes(b"approved")
            contact.write_bytes(b"contact")
            receipt = canary / "receipt.json"
            receipt.write_text(json.dumps({
                "status": "machine_verified_pending_human_review",
                "human_approval_claimed": False,
                "cases": [{"family": family, "template_id": f"hd-talking-head/semantic-state-{family}"}
                          for family in module.FAMILIES],
                "montage": {"path": montage.name, "sha256": module.sha256(montage)},
                "contact_sheet": {"path": contact.name, "sha256": module.sha256(contact)},
            }), encoding="utf-8")
            review = canary / "review.json"
            review.write_text(json.dumps({
                "schema_version": 1, "status": "approved", "human_approval_claimed": True,
                "scope": "five-family SemanticState avatar-composite canary", "reviewer": "User",
                "reviewed_at": "2026-09-07T06:20:55+08:00",
                "approval_reference": "thread-test-user-confirmed-avatar-canary",
                "families": list(module.FAMILIES),
                "template_ids": [f"hd-talking-head/semantic-state-{family}" for family in module.FAMILIES],
                "canary_receipt": {"path": receipt.relative_to(root).as_posix(), "sha256": module.sha256(receipt)},
                "montage": {"path": montage.relative_to(root).as_posix(), "sha256": module.sha256(montage)},
                "contact_sheet": {"path": contact.relative_to(root).as_posix(), "sha256": module.sha256(contact)},
            }), encoding="utf-8")
            montage.write_bytes(b"changed-after-approval")

            with self.assertRaisesRegex(ValueError, "montage SHA-256"):
                module.validate_human_approval(root, review)


if __name__ == "__main__":
    unittest.main()

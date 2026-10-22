"""A historical poster is not proof that new content reaches its renderer."""
import copy
import importlib.util
import json
import hashlib
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("execution_registry_test", SKILL / "scripts/verify_broll_template.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class TemplateExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.item = json.loads((SKILL / "references/verified-template-registry.json").read_text())["templates"][0]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        assets = Path("assets/verified-templates/html-video/frame-data-rollup")
        shutil.copytree(SKILL / assets, self.root / assets)
        (self.root / "scripts").mkdir()
        shutil.copyfile(SKILL / "scripts/render_data_rollup.cjs", self.root / "scripts/render_data_rollup.cjs")

    def verify(self):
        self.item["verification_id"] = verifier._verification_id(self.item)
        return verifier._verify_template(self.root, self.item)

    def changed_file(self, ref, change):
        path = self.root / ref["path"]
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False))
        ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def case(self, index=0):
        return self.item["execution_qa"]["cases"][index]

    def test_historical_sample_without_two_input_execution_proof_is_rejected(self):
        self.item.pop("execution_qa", None)
        with self.assertRaises(verifier.RegistryError):
            self.verify()

    def test_real_shipped_pair_passes_media_probe_without_renderer(self):
        self.assertEqual(self.verify()["execution_qa"]["status"], "reviewed")

    def test_execution_cases_must_be_two_distinct_runs(self):
        for cases in [[], [self.case()], [self.case(), self.case()]]:
            with self.subTest(count=len(cases)):
                original = self.item["execution_qa"]["cases"]
                self.item["execution_qa"]["cases"] = copy.deepcopy(cases)
                with self.assertRaisesRegex(verifier.RegistryError, "execution_qa"):
                    self.verify()
                self.item["execution_qa"]["cases"] = original

    def test_unreviewed_execution_pair_is_rejected(self):
        self.item["execution_qa"]["status"] = "pending"
        with self.assertRaisesRegex(verifier.RegistryError, "execution_qa"):
            self.verify()

    def test_content_paths_must_resolve_to_real_varying_props(self):
        for paths in [[], ["/canvas/duration_in_frames"], ["/props/absent"],
                      ["/props/foreground"], ["/props/data/items", "/props/data/items"]]:
            with self.subTest(paths=paths):
                self.item["execution_qa"]["content_paths"] = paths
                with self.assertRaisesRegex(verifier.RegistryError, "content_paths"):
                    self.verify()

    def test_different_canvas_does_not_count_as_different_content(self):
        brief_a = json.loads((self.root / self.case()["brief"]["path"]).read_text())
        self.changed_file(self.case(1)["brief"], lambda b: b.update(props=brief_a["props"]))
        with self.assertRaisesRegex(verifier.RegistryError, "content_paths|brief"):
            self.verify()

    def test_same_mp4_cannot_be_reused_as_second_output(self):
        self.case(1)["sample"] = copy.deepcopy(self.case()["sample"])
        with self.assertRaisesRegex(verifier.RegistryError, "sample|output"):
            self.verify()

    def test_recipe_source_and_capacity_are_bound_to_current_template(self):
        for key, value in [("source_sha256", "0" * 64), ("capacity", {"min_units": 1, "max_units": 99}),
                           ("primary_renderer", "HyperFrames")]:
            with self.subTest(key=key):
                ref = self.case()["recipe"]
                original = (self.root / ref["path"]).read_bytes()
                self.changed_file(ref, lambda r: r["components"][0].update({key: value}))
                with self.assertRaisesRegex(verifier.RegistryError, "recipe"):
                    self.verify()
                (self.root / ref["path"]).write_bytes(original)
                ref["sha256"] = hashlib.sha256(original).hexdigest()

    def test_frozen_request_must_match_actual_brief(self):
        self.changed_file(self.case()["recipe"], lambda r: r["components"][0]["invocation_record"]["template_request"].update(information_units=4))
        with self.assertRaisesRegex(verifier.RegistryError, "brief|request"):
            self.verify()

    def test_failed_or_unfinished_invocations_do_not_qualify(self):
        for key, value in [("exit_code", 1), ("exit_code", False), ("timed_out", True),
                           ("pid", 0), ("unresolved_process_group", True),
                           ("brief_sha256", "0" * 64), ("output_sha256", "0" * 64),
                           ("primary_renderer", "HyperFrames")]:
            with self.subTest(key=key):
                ref = self.case()["receipt"]
                original = (self.root / ref["path"]).read_bytes()
                self.changed_file(ref, lambda r: r["artifact"]["invocation_evidence"].update({key: value}))
                with self.assertRaisesRegex(verifier.RegistryError, "receipt|invocation"):
                    self.verify()
                (self.root / ref["path"]).write_bytes(original)
                ref["sha256"] = hashlib.sha256(original).hexdigest()

    def test_changed_executable_requires_new_execution_evidence(self):
        path = self.root / "scripts/render_data_rollup.cjs"
        path.write_bytes(path.read_bytes() + b"\n// changed\n")
        with self.assertRaisesRegex(verifier.RegistryError, "entrypoint"):
            self.verify()

    def test_actual_video_frame_count_not_just_receipt_is_checked(self):
        self.changed_file(self.case()["receipt"], lambda r: r["artifact"]["media_probe"].update(frame_count=95))
        with self.assertRaisesRegex(verifier.RegistryError, "probe|frame"):
            self.verify()

    def test_case_frames_must_have_ordered_in_range_timestamps(self):
        self.case()["frame_evidence"][2]["timestamp_sec"] = 4
        with self.assertRaisesRegex(verifier.RegistryError, "frame_evidence"):
            self.verify()

    def test_static_same_keyframe_cannot_stand_for_changed_content(self):
        self.case(1)["frame_evidence"][1] = copy.deepcopy(self.case()["frame_evidence"][1])
        with self.assertRaisesRegex(verifier.RegistryError, "stable|frame_evidence"):
            self.verify()

    def test_proof_paths_cannot_escape_package(self):
        self.case()["brief"]["path"] = "../brief.json"
        with self.assertRaisesRegex(verifier.RegistryError, "path|relative"):
            self.verify()

    def test_proof_paths_cannot_use_symlinks(self):
        ref = self.case()["brief"]
        path = self.root / ref["path"]
        original = path.with_suffix(".backup")
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaisesRegex(verifier.RegistryError, "symbolic"):
            self.verify()

    def test_damaged_proof_is_a_clear_registry_failure(self):
        ref = self.case()["receipt"]
        path = self.root / ref["path"]
        path.write_bytes(b"not json")
        ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(verifier.RegistryError, "receipt.*JSON"):
            self.verify()

    def test_source_snapshot_must_match_template_native_identity(self):
        self.changed_file(self.item["execution_qa"]["source_registry"], lambda r: r["templates"][0].update(source_sha256="0" * 64))
        with self.assertRaisesRegex(verifier.RegistryError, "source_registry"):
            self.verify()

    def test_nonimage_files_cannot_stand_for_keyframes(self):
        for case in self.item["execution_qa"]["cases"]:
            for frame in case["frame_evidence"]:
                frame.update(case["brief"])
        with self.assertRaisesRegex(verifier.RegistryError, "frame_evidence"):
            self.verify()

    def test_keyframe_pixels_must_match_sample_at_recorded_time(self):
        self.case()["frame_evidence"][0]["timestamp_sec"] = 0.25
        with self.assertRaisesRegex(verifier.RegistryError, "frame_evidence"):
            self.verify()

    def test_keyframe_time_must_be_on_frame_boundary(self):
        self.case()["frame_evidence"][0]["timestamp_sec"] = 0.501
        with self.assertRaisesRegex(verifier.RegistryError, "frame_evidence"):
            self.verify()

    def test_receipt_must_bind_complete_recipe_hash(self):
        self.changed_file(self.case()["recipe"], lambda r: r.update(strategy_revision=2))
        with self.assertRaisesRegex(verifier.RegistryError, "recipe"):
            self.verify()

    def test_receipt_input_hash_cannot_be_fabricated(self):
        self.changed_file(self.case()["receipt"], lambda r: r["artifact"].update(input_sha256="0" * 64))
        with self.assertRaisesRegex(verifier.RegistryError, "recipe"):
            self.verify()

    def test_receipt_artifact_contract_must_match_recipe(self):
        self.changed_file(self.case()["receipt"], lambda r: r["artifact"]["artifact_contract"].update(alpha=True))
        with self.assertRaisesRegex(verifier.RegistryError, "recipe"):
            self.verify()

    def test_nested_malformed_object_is_a_clear_registry_failure(self):
        self.changed_file(self.case()["receipt"], lambda r: r["artifact"].update(qa=[]))
        with self.assertRaisesRegex(verifier.RegistryError, "malformed"):
            self.verify()

    def test_same_decoded_picture_is_not_distinct_content(self):
        # Isolate the distinction between encoded bytes and decoded pixels.
        # All existing hash/media/frame binding checks still run against files.
        original = verifier._decoded_frame_hashes

        def same_stable_pixels(path, indices=None):
            hashes = original(path, indices)
            if indices is not None:
                hashes[1] = "a" * 64
            elif path.name == "stable.png":
                hashes[0] = "a" * 64
            return hashes

        with patch.object(verifier, "_decoded_frame_hashes", side_effect=same_stable_pixels):
            with self.assertRaisesRegex(verifier.RegistryError, "distinct"):
                self.verify()


if __name__ == "__main__":
    unittest.main()

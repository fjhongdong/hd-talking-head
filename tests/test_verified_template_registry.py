#!/usr/bin/env python3
"""Contract tests for the verified third-party B-roll template registry."""

from __future__ import annotations

import json
import hashlib
import copy
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "verify_broll_template.py"
REGISTRY = SKILL_ROOT / "references" / "verified-template-registry.json"
SPEC = importlib.util.spec_from_file_location("template_verifier", SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _refresh_verification_id(template: dict[str, object]) -> None:
    payload = {key: value for key, value in template.items() if key != "verification_id"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    template["verification_id"] = hashlib.sha256(canonical).hexdigest()


class VerifiedTemplateRegistryTests(unittest.TestCase):
    def local_candidate(self, *, process: bool = False) -> dict[str, object]:
        item = copy.deepcopy(json.loads(REGISTRY.read_text())["templates"][0])
        item.pop("execution_qa")
        item["template_origin"] = "verified_local_canonical"
        item["template_id"] = "local/process-relations" if process else "local/viewpoint-comparison"
        item["adaptation_level"] = "structural"
        item["upstream"] = {
            "project": "hd-talking-head-local-canonical",
            "repository": ".",
            "commit": "local-canonical-v1",
        }
        if process:
            item["render_contract"]["composition_id"] = "process-relations"
            frames = item["visual_qa"]["frame_evidence"]
            item["action_sequence_qa"] = {
                "status": "approved",
                "reviewed_at": "2026-09-05T10:00:00+08:00",
                "reviewer": "human",
                "events": [
                    {
                        "event": name,
                        "timestamp_sec": frame["timestamp_sec"],
                        "path": frame["path"],
                        "sha256": frame["sha256"],
                    }
                    for name, frame in zip(
                        ("sources_visible", "connections_complete", "result_visible"),
                        frames,
                    )
                ],
            }
        _refresh_verification_id(item)
        return item

    def test_registry_accepts_only_verified_third_party_and_local_canonical(self) -> None:
        with patch.object(VERIFIER, "_probe_video", return_value={
            "codec": "h264", "width": 1080, "height": 1920, "fps": 24.0,
            "duration": 4.0,
        }):
            checked = VERIFIER._verify_template(
                SKILL_ROOT, self.local_candidate(), require_execution=False,
            )
        self.assertEqual(checked["template_origin"], "verified_local_canonical")
        for origin in ("custom_fallback", "unverified_external", "local"):
            item = self.local_candidate()
            item["template_origin"] = origin
            _refresh_verification_id(item)
            with self.subTest(origin=origin), self.assertRaisesRegex(
                VERIFIER.RegistryError, "template_origin"
            ):
                VERIFIER._verify_template(SKILL_ROOT, item, require_execution=False)

    def test_local_canonical_upstream_identity_is_fixed(self) -> None:
        for field, value in (
            ("project", "another-project"),
            ("repository", "assets/local-copy"),
            ("commit", ""),
        ):
            item = self.local_candidate()
            item["upstream"][field] = value
            _refresh_verification_id(item)
            with self.subTest(field=field), self.assertRaisesRegex(
                VERIFIER.RegistryError, "upstream"
            ):
                VERIFIER._verify_template(SKILL_ROOT, item, require_execution=False)

    def test_structural_adaptation_is_local_only(self) -> None:
        item = self.local_candidate()
        with patch.object(VERIFIER, "_probe_video", return_value={
            "codec": "h264", "width": 1080, "height": 1920, "fps": 24.0,
            "duration": 4.0,
        }):
            VERIFIER._verify_template(SKILL_ROOT, item, require_execution=False)
        item["template_origin"] = "verified_third_party"
        item["upstream"] = {
            "project": "html-video",
            "repository": "https://github.com/nexu-io/html-video.git",
            "commit": "fixture",
        }
        _refresh_verification_id(item)
        with self.assertRaisesRegex(VERIFIER.RegistryError, "structural"):
            VERIFIER._verify_template(SKILL_ROOT, item, require_execution=False)

    def test_process_template_requires_action_sequence_qa(self) -> None:
        item = self.local_candidate(process=True)
        item.pop("action_sequence_qa")
        _refresh_verification_id(item)
        with self.assertRaisesRegex(VERIFIER.RegistryError, "action_sequence_qa"):
            VERIFIER._verify_template(SKILL_ROOT, item, require_execution=False)

    def test_prequalification_snapshots_can_bind_without_self_certifying_production(self) -> None:
        cases = (
            (
                "hyperframes/notification-cascade",
                "assets/verified-templates/hyperframes/notification-cascade/"
                "qualification/source-registry.json",
            ),
            (
                "hyperframes/chatgpt-exchange",
                "assets/verified-templates/hyperframes/chatgpt-exchange/"
                "qualification/source-registry.json",
            ),
        )
        for template_id, relative in cases:
            with self.subTest(template_id=template_id):
                path = SKILL_ROOT / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                candidate = payload["templates"][0]
                binding = {key: candidate[key] for key in VERIFIER.PROVENANCE_FIELDS}
                digest = hashlib.sha256(path.read_bytes()).hexdigest()

                checked = VERIFIER.verify_candidate_binding(binding, relative, digest)

                self.assertEqual(checked["template_id"], template_id)
                with self.assertRaises(VERIFIER.RegistryError):
                    VERIFIER.verify_candidate_binding(binding, relative, "0" * 64)
                with self.assertRaises(VERIFIER.RegistryError):
                    VERIFIER.verify_registered_binding(binding)

    def probe_payload(self) -> dict:
        return {"streams": [{
            "codec_name": "h264", "width": 1080, "height": 1920,
            "r_frame_rate": "24/1", "avg_frame_rate": "24/1",
            "sample_aspect_ratio": "1:1", "display_aspect_ratio": "9:16",
            "nb_frames": "96",
        }], "format": {"duration": "4.0"}}

    def probe(self, payload: dict) -> dict:
        process = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with patch.object(VERIFIER.subprocess, "run", return_value=process) as run:
            result = VERIFIER._probe_video(Path("sample.mp4"))
        self.assertGreater(run.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 30)
        return result

    def test_probe_is_bounded_and_reads_display_geometry(self) -> None:
        result = self.probe(self.probe_payload())
        self.assertEqual(result["sar"], "1:1")
        self.assertEqual(result["dar"], "9:16")

    def test_probe_rejects_display_rotation_and_invalid_rotation_metadata(self) -> None:
        for value in [-90, 90, 180, "NaN", "Infinity", "invalid"]:
            for metadata in [{"side_data_list": [{"rotation": value}]},
                             {"tags": {"rotate": str(value)}}]:
                with self.subTest(metadata=metadata):
                    payload = self.probe_payload()
                    payload["streams"][0].update(metadata)
                    with self.assertRaises(VERIFIER.RegistryError):
                        self.probe(payload)

    def test_probe_requests_rotation_metadata_and_accepts_identity_rotation(self) -> None:
        payload = self.probe_payload()
        payload["streams"][0]["side_data_list"] = [{"rotation": 0}]
        process = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with patch.object(VERIFIER.subprocess, "run", return_value=process) as run:
            result = VERIFIER.verify_production_video(Path("sample.mp4"), expected_frames=96)
        entries = run.call_args.args[0][run.call_args.args[0].index("-show_entries") + 1]
        self.assertIn("stream_side_data=rotation", entries)
        self.assertIn("stream_tags=rotate", entries)
        self.assertEqual(result["rotation"], 0)

    def test_probe_rejects_non_square_or_unknown_pixels(self) -> None:
        for key, value in [("sample_aspect_ratio", "2:1"),
                           ("sample_aspect_ratio", "N/A"),
                           ("display_aspect_ratio", "3:4")]:
            with self.subTest(key=key, value=value):
                payload = self.probe_payload()
                payload["streams"][0][key] = value
                with self.assertRaises(VERIFIER.RegistryError):
                    self.probe(payload)

    def test_probe_rejects_invalid_rates_and_durations(self) -> None:
        for value in ["0/0", "0/1", "-24/1", "NaN", "Infinity"]:
            with self.subTest(fps=value):
                payload = self.probe_payload()
                payload["streams"][0]["r_frame_rate"] = value
                with self.assertRaises(VERIFIER.RegistryError):
                    self.probe(payload)
        for value in ["NaN", "Infinity", "-1", "0"]:
            with self.subTest(duration=value):
                payload = self.probe_payload()
                payload["format"]["duration"] = value
                with self.assertRaises(VERIFIER.RegistryError):
                    self.probe(payload)

    def test_probe_reports_timeout_missing_binary_and_corrupt_payload(self) -> None:
        for error in [subprocess.TimeoutExpired("ffprobe", 20), FileNotFoundError("ffprobe")]:
            with self.subTest(error=type(error).__name__):
                with patch.object(VERIFIER.subprocess, "run", side_effect=error):
                    with self.assertRaisesRegex(VERIFIER.RegistryError, "ffprobe"):
                        VERIFIER._probe_video(Path("sample.mp4"))
        for payload in [{}, {"streams": []}, {"streams": "invalid"},
                        {"streams": [None]}, {"streams": [{}], "format": None}]:
            with self.subTest(payload=payload):
                with self.assertRaises(VERIFIER.RegistryError):
                    self.probe(payload)

    def test_artifact_contract_rejects_non_finite_or_boolean_numbers(self) -> None:
        original = json.loads(REGISTRY.read_text())["templates"][0]
        for key in ["fps", "duration_min_sec", "duration_max_sec"]:
            for value in [float("nan"), float("inf"), True, 0, -1]:
                with self.subTest(key=key, value=value):
                    item = copy.deepcopy(original)
                    item["artifact_contract"][key] = value
                    _refresh_verification_id(item)
                    with self.assertRaisesRegex(VERIFIER.RegistryError, "artifact_contract"):
                        VERIFIER._verify_template(SKILL_ROOT, item)

    def test_qa_frames_must_be_ordered_and_before_end_of_video(self) -> None:
        original = json.loads(REGISTRY.read_text())["templates"][0]
        for times in [(2, 1, 3.8), (.5, .5, 3.8), (.5, 2, 4.0)]:
            with self.subTest(times=times):
                item = copy.deepcopy(original)
                for frame, time in zip(item["visual_qa"]["frame_evidence"], times):
                    frame["timestamp_sec"] = time
                _refresh_verification_id(item)
                with self.assertRaisesRegex(VERIFIER.RegistryError, "frame_evidence"):
                    VERIFIER._verify_template(SKILL_ROOT, item)

    def test_production_video_requires_24fps_and_current_frame_count(self) -> None:
        for rate, frames, duration in [(30, 120, 4), (24, 95, 4), (24, 96, 5)]:
            with self.subTest(rate=rate, frames=frames, duration=duration):
                payload = self.probe_payload()
                payload["streams"][0].update(r_frame_rate=f"{rate}/1",
                    avg_frame_rate=f"{rate}/1", nb_frames=str(frames))
                payload["format"]["duration"] = str(duration)
                process = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
                with patch.object(VERIFIER.subprocess, "run", return_value=process):
                    with self.assertRaises(VERIFIER.RegistryError):
                        VERIFIER.verify_production_video(Path("sample.mp4"), expected_frames=96)
        process = subprocess.CompletedProcess([], 0, json.dumps(self.probe_payload()), "")
        with patch.object(VERIFIER.subprocess, "run", return_value=process):
            self.assertEqual(VERIFIER.verify_production_video(
                Path("sample.mp4"), expected_frames=96)["frame_count"], 96)

    def test_default_registry_is_resolved_from_the_package_not_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--json"], cwd=temporary,
                check=False, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["verified_count"], 14)

    def test_cli_rejects_wrong_approved_render_window(self) -> None:
        record = json.loads(REGISTRY.read_text())["templates"][0]
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--production-video", str(SKILL_ROOT / record["sample_path"]),
            "--expected-frames", "120", "--json",
        ], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["scope"], "production_media")
        self.assertIn("frame_count", report["failures"][0])

    def run_verifier(self, registry: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--registry", str(registry), "--json"],
            cwd=SKILL_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_shipped_registry_contains_a_verified_native_vertical_template(self) -> None:
        result = self.run_verifier(REGISTRY)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertGreaterEqual(report["verified_count"], 1)
        self.assertEqual(report["failures"], [])
        template = report["verified"][0]
        self.assertEqual(template["template_origin"], "verified_third_party")
        self.assertEqual(template["artifact_contract"]["width"], 1080)
        self.assertEqual(template["artifact_contract"]["height"], 1920)
        self.assertEqual(template["visual_qa"]["status"], "approved")

    def test_chatgpt_exchange_contract_is_narrow_and_fully_exercised(self) -> None:
        records = {
            item["template_id"]: item
            for item in json.loads(REGISTRY.read_text(encoding="utf-8"))["templates"]
        }
        template = records["hyperframes/chatgpt-exchange"]

        self.assertEqual(template["adaptation_level"], "content_reflow")
        self.assertEqual(
            template["semantic_families"],
            ["ai_dialogue_comparison", "four_factor_comparison", "prompt_to_table"],
        )
        self.assertEqual(template["capacity"], {"min_units": 4, "max_units": 4})
        self.assertEqual(
            template["artifact_contract"],
            {
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "duration_min_sec": 14.9,
                "duration_max_sec": 14.92,
                "codec": "h264",
            },
        )
        execution = template["execution_qa"]
        self.assertEqual(execution["status"], "reviewed")
        self.assertEqual(len(execution["content_paths"]), 22)
        self.assertEqual(len(execution["cases"]), 2)

    def test_tampered_sample_hash_is_rejected(self) -> None:
        payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
        payload["templates"][0]["sample_sha256"] = "0" * 64
        _refresh_verification_id(payload["templates"][0])

        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.json"
            registry.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_verifier(registry)

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(any("sample_sha256" in item for item in report["failures"]))

    def test_structural_adaptation_cannot_claim_verified_third_party_status(self) -> None:
        payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
        payload["templates"][0]["adaptation_level"] = "structural"
        _refresh_verification_id(payload["templates"][0])

        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.json"
            registry.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_verifier(registry)

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(any("adaptation_level" in item for item in report["failures"]))

    def test_visual_qa_requires_entry_stable_and_exit_evidence(self) -> None:
        payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
        payload["templates"][0]["visual_qa"]["frame_evidence"].pop()
        _refresh_verification_id(payload["templates"][0])

        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.json"
            registry.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_verifier(registry)

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(any("frame_evidence" in item for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()

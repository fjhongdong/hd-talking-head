from __future__ import annotations

import copy
import hashlib
import unittest

from edit.hd.tests.test_render_span import v4_plan
from edit.hd.tests.test_talkcraft_binding import TalkCraftBindingTests
from edit.hd.tools import (
    contract_artifacts,
    render_span,
    state,
    talkcraft_binding,
    talkcraft_contract,
    visual_plan,
    visual_span_contract,
)


_STABLE_APPROVAL_KEYS = {
    "job_id", "visual_plan_artifact_sha256",
    "production_brief_bundle_artifact_sha256",
    "production_brief_bundle_sha256", "registry_version", "registry_sha256",
}


def _job_file(path, job_dir):
    return {
        "job_path": path.relative_to(job_dir).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def _rendered_chunk(fixture: TalkCraftBindingTests) -> dict[str, object]:
    job_dir = fixture.job.job_dir
    chunk = fixture.plan["render_spans"][0]["chunks"][0]
    span = fixture.plan["render_spans"][0]
    output_dir = job_dir / "08-visual-canary/spans/span-001"
    output_dir.mkdir(parents=True, exist_ok=True)
    video = output_dir / "chunk-001.mp4"
    component = output_dir / "component.mov"
    video.write_bytes(b"assembled-span-chunk")
    component.write_bytes(b"talkcraft-component")
    component_record = _job_file(component, job_dir)
    production_brief = fixture.bundle["briefs"][0]["brief"]
    artifact = {
        "schema_version": 1,
        "status": "success",
        "job_id": fixture.job.job_id,
        "segment_id": "seg-001",
        "component_id": "component-1",
        "kind": "code_generated",
        "strategy_revision": 1,
        "media_type": "video",
        "render_window": {
            "start_frame": 0,
            "end_frame": 72,
            "z_index": 1,
            "layout_slot": "main",
            "opacity": 1.0,
            "safe_zone": {"top": 120, "bottom": 360, "left": 48, "right": 48},
        },
        "z_index": 1,
        "layout_slot": "main",
        "opacity": 1.0,
        "safe_zone": {"top": 120, "bottom": 360, "left": 48, "right": 48},
        "artifact_contract": {
            "width": 1080, "height": 1920, "fps": 24, "alpha": True,
        },
        "source_media_type": "animation",
        "artifact_media_type": "video",
        "media_probe": {
            "container": "mov", "codec": "prores_ks",
            "pixel_format": "yuva444p10le", "width": 1080, "height": 1920,
            "fps": 24, "frame_count": 72, "duration": 3.0,
        },
        "input_sha256": "a" * 64,
        "job_path": component_record["job_path"],
        "byte_count": component_record["bytes"],
        "output_sha256": component_record["sha256"],
        "invocation_evidence": {
            "span_id": "span-001",
            "chunk_id": "chunk-001",
            "spec_sha256": chunk["spec_sha256"],
            "production_brief_sha256": contract_artifacts.sha256_json(
                production_brief
            ),
            "production_brief_bundle_sha256": fixture.bundle["bundle_sha256"],
            "output_job_path": component_record["job_path"],
            "output_sha256": component_record["sha256"],
        },
        "qa": {"passed": True, "checks": ["fixture"]},
        "error_code": None,
    }
    keyframes = {}
    for name, frame in (("entry", 1), ("hold", 36), ("exit", 70)):
        path = output_dir / f"{name}.png"
        path.write_bytes(name.encode("utf-8"))
        keyframes[name] = {**_job_file(path, job_dir), "frame": frame}
    unsigned = {
        "schema_version": "rendered-span-chunk/v1",
        "visual_plan_sha256": fixture.plan["visual_plan_sha256"],
        "span_id": "span-001",
        "chunk_id": "chunk-001",
        "spec_sha256": chunk["spec_sha256"],
        "scene_brief_sha256": span["scene_brief_sha256"],
        "production_brief_bundle_sha256": fixture.bundle["bundle_sha256"],
        "video": _job_file(video, job_dir),
        "frames": 72,
        "component_artifacts": [{
            "component_id": "component-1",
            "execution_target": {
                "kind": "component",
                "segment_id": "seg-001",
                "component_id": "component-1",
            },
            "artifact": artifact,
        }],
        "output_probe": {
            "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
            "width": 1080, "height": 1920, "fps": 24,
            "frame_count": 72, "duration": 3.0, "audio_streams": 0,
        },
        "keyframes": keyframes,
        "renderer": {
            "dependency_id": talkcraft_contract.DEPENDENCY_ID,
            "primary_renderer": talkcraft_contract.PRIMARY_RENDERER,
            "adapter_id": "talkcraft-reference-v1",
            "adapter_version": "1.0.0",
            "entrypoint": "edit/hd/integrations/talkcraft/runtime/render.mjs",
            "implementation_sha256": "b" * 64,
        },
    }
    return {**unsigned, "render_identity": contract_artifacts.sha256_json(unsigned)}


def _manifest(fixture: TalkCraftBindingTests) -> dict[str, object]:
    selected = visual_span_contract.select_canary_chunks(fixture.plan)
    binding = talkcraft_binding.bind_approved_brief_bundle(
        fixture.job,
        fixture.request,
        fixture.bundle,
        registry_path=fixture.registry_path,
    )
    track_path = fixture.job.job_dir / "08-visual-canary/talkcraft-track.mp4"
    track_path.parent.mkdir(parents=True, exist_ok=True)
    track_path.write_bytes(b"complete-canary-track")
    unsigned = {
        "schema_version": "talkcraft-span-canary-manifest/v1",
        "job_id": fixture.job.job_id,
        "visual_plan_sha256": fixture.plan["visual_plan_sha256"],
        "assembly_spec": visual_span_contract.build_assembly_spec(
            fixture.plan, selected, kind="canary"
        ),
        "chunks": [{
            "span_id": "span-001",
            "chunk_id": "chunk-001",
            "visual_approval": {
                key: copy.deepcopy(binding[key]) for key in _STABLE_APPROVAL_KEYS
            },
            "rendered": _rendered_chunk(fixture),
        }],
        "track": _job_file(track_path, fixture.job.job_dir),
        "track_probe": {
            "container": "mp4", "codec": "h264", "pixel_format": "yuv420p",
            "width": 1080, "height": 1920, "fps": 24,
            "frame_count": 72, "duration": 3.0, "audio_streams": 0,
        },
    }
    return {**unsigned, "canary_sha256": contract_artifacts.sha256_json(unsigned)}


def _approve_canary(fixture: TalkCraftBindingTests) -> dict[str, object]:
    manifest = _manifest(fixture)
    path = (
        fixture.job.job_dir
        / "08-visual-canary/talkcraft-span-canary-manifest.json"
    )
    contract_artifacts.write_json_artifact(path, manifest)
    state.mark_ready(fixture.job, "visual_canary", (path,))
    state.approve(fixture.job, "visual_canary")
    fixture.job = state.load_job(fixture.job.job_dir)
    return manifest


def _assets_manifest(
    fixture: TalkCraftBindingTests,
    canary: dict[str, object],
) -> dict[str, object]:
    record = next(
        item for item in fixture.job.stages["visual_canary"]["artifacts"]
        if item["path"]
        == "08-visual-canary/talkcraft-span-canary-manifest.json"
    )
    chunk = canary["chunks"][0]
    unsigned = {
        "schema_version": "talkcraft-chunk-assets-manifest/v1",
        "artifact_kind": "talkcraft_chunk_assets",
        "scope": "all_talkcraft_chunks_in_plan",
        "content_role": "final_composited_chunks",
        "job_id": fixture.job.job_id,
        "visual_plan_sha256": fixture.plan["visual_plan_sha256"],
        "chunks": [{
            "span_id": chunk["span_id"],
            "chunk_id": chunk["chunk_id"],
            "visual_approval": copy.deepcopy(chunk["visual_approval"]),
            "rendered": copy.deepcopy(chunk["rendered"]),
            "materialized_mp4": copy.deepcopy(chunk["rendered"]["video"]),
            "source": {
                "kind": "approved_canary",
                "manifest": {
                    "job_path": record["path"],
                    "sha256": record["sha256"],
                    "bytes": record["bytes"],
                },
            },
        }],
    }
    return {**unsigned, "assets_sha256": contract_artifacts.sha256_json(unsigned)}


class VisualSpanContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TalkCraftBindingTests()
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_complete_canary_manifest_replays_approved_bytes(self) -> None:
        manifest = _manifest(self.fixture)
        self.assertEqual(
            visual_span_contract.validate_canary_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            ),
            manifest,
        )

    def test_manifest_rejects_unvalidated_extra_chunk_and_audio(self) -> None:
        manifest = _manifest(self.fixture)
        manifest["chunks"].append("not-a-chunk")
        with self.assertRaises(visual_span_contract.VisualSpanContractError):
            visual_span_contract.validate_canary_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )

    def test_manifest_rejects_non_finite_track_duration(self) -> None:
        manifest = _manifest(self.fixture)
        manifest["track_probe"]["duration"] = float("nan")
        with self.assertRaisesRegex(
            visual_span_contract.VisualSpanContractError, "track probe"
        ):
            visual_span_contract.validate_canary_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )

    def test_manifest_rejects_boolean_audio_stream_count(self) -> None:
        manifest = _manifest(self.fixture)
        manifest["track_probe"]["audio_streams"] = False
        unsigned = {
            key: value for key, value in manifest.items() if key != "canary_sha256"
        }
        manifest["canary_sha256"] = contract_artifacts.sha256_json(unsigned)
        with self.assertRaisesRegex(
            visual_span_contract.VisualSpanContractError, "track probe"
        ):
            visual_span_contract.validate_canary_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )

    def test_selection_and_assembly_preserve_real_span_boundaries(self) -> None:
        plan = v4_plan(self.fixture.bundle["briefs"][0]["brief"]["card_id"])
        targets = plan["render_spans"][0]["chunks"][0]["execution_targets"]
        plan["render_spans"][0]["chunks"] = [
            {
                "chunk_id": "chunk-001", "start_frame": 0, "end_frame": 24,
                "execution_targets": copy.deepcopy(targets),
            },
            {
                "chunk_id": "chunk-002", "start_frame": 24, "end_frame": 72,
                "execution_targets": copy.deepcopy(targets),
            },
        ]
        for chunk in plan["render_spans"][0]["chunks"]:
            chunk["spec_sha256"] = render_span.chunk_spec_sha256(
                "span-001", chunk
            )
        unsigned = {
            key: value for key, value in plan.items() if key != "visual_plan_sha256"
        }
        plan["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        plan = visual_plan.validate_visual_plan(plan)
        selected = visual_span_contract.select_canary_chunks(plan)
        assembly = visual_span_contract.build_assembly_spec(plan, selected)
        self.assertTrue(assembly["chunks"][0]["apply_span_entry_alpha"])
        self.assertFalse(assembly["chunks"][0]["apply_span_exit_alpha"])
        self.assertFalse(assembly["chunks"][1]["apply_span_entry_alpha"])
        self.assertTrue(assembly["chunks"][1]["apply_span_exit_alpha"])
        self.assertFalse(assembly["chunk_boundary_alpha"])

    def test_chunk_assets_reuse_approved_canary_bytes(self) -> None:
        canary = _approve_canary(self.fixture)
        manifest = _assets_manifest(self.fixture, canary)
        self.assertEqual(
            visual_span_contract.validate_chunk_assets_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                approved_canary=canary,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            ),
            manifest,
        )

    def test_chunk_assets_cannot_rerender_an_approved_canary(self) -> None:
        canary = _approve_canary(self.fixture)
        manifest = _assets_manifest(self.fixture, canary)
        manifest["chunks"][0]["source"] = {"kind": "fresh"}
        unsigned = {
            key: value for key, value in manifest.items() if key != "assets_sha256"
        }
        manifest["assets_sha256"] = contract_artifacts.sha256_json(unsigned)
        with self.assertRaisesRegex(
            visual_span_contract.VisualSpanContractError,
            "must be reused",
        ):
            visual_span_contract.validate_chunk_assets_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                approved_canary=canary,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )

    def test_chunk_assets_reject_incomplete_coverage_and_changed_bytes(self) -> None:
        canary = _approve_canary(self.fixture)
        manifest = _assets_manifest(self.fixture, canary)
        manifest["chunks"] = []
        unsigned = {
            key: value for key, value in manifest.items() if key != "assets_sha256"
        }
        manifest["assets_sha256"] = contract_artifacts.sha256_json(unsigned)
        with self.assertRaisesRegex(
            visual_span_contract.VisualSpanContractError,
            "cover every",
        ):
            visual_span_contract.validate_chunk_assets_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                approved_canary=canary,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )
        manifest = _assets_manifest(self.fixture, canary)
        replacement = self.fixture.job.job_dir / "09-visual-assets/reencoded.mp4"
        replacement.parent.mkdir(parents=True, exist_ok=True)
        replacement.write_bytes(b"not-the-approved-bytes")
        manifest["chunks"][0]["materialized_mp4"] = _job_file(
            replacement, self.fixture.job.job_dir
        )
        unsigned = {
            key: value for key, value in manifest.items() if key != "assets_sha256"
        }
        manifest["assets_sha256"] = contract_artifacts.sha256_json(unsigned)
        with self.assertRaisesRegex(
            visual_span_contract.VisualSpanContractError,
            "exact byte reuse",
        ):
            visual_span_contract.validate_chunk_assets_manifest(
                self.fixture.job,
                self.fixture.plan,
                manifest,
                approved_canary=canary,
                brief_bundles={"chunk-001": self.fixture.bundle},
                registry_path=self.fixture.registry_path,
            )


if __name__ == "__main__":
    unittest.main()

"""Frame-level composition tests for approved component artifacts."""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from edit.hd.tools import broll_component_executor, segment_render, visual_strategy
from edit.hd.tests.test_avatar_contract import avatar_fixture


KINDS = (
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
)


class _Job:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.job_dir = root / "job"
        self.job_dir.mkdir()
        self.job_id = "job-001"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _window(
    *,
    start: int,
    end: int,
    z_index: int,
    slot: str,
    opacity: float = 1.0,
    bottom: int = 320,
) -> dict[str, object]:
    return {
        "start_frame": start,
        "end_frame": end,
        "z_index": z_index,
        "layout_slot": slot,
        "opacity": opacity,
        "safe_zone": {"top": 120, "bottom": bottom, "left": 40, "right": 40},
    }


def _binding(kind: str, component_id: str, sha256: str) -> dict[str, object]:
    if kind == "local_material":
        return {
            "material_id": component_id,
            "job_path": f"source/{component_id}.png",
            "sha256": sha256,
        }
    if kind == "official_material":
        return {
            "source_id": component_id,
            "publisher": "Example Institute",
            "source_url": "https://example.org/report",
            "snapshot_path": f"source/{component_id}.png",
            "fetched_at": "2026-08-31T12:00:00+08:00",
            "sha256": sha256,
        }
    if kind == "external_stock":
        return {
            "provider": "Pexels",
            "provider_asset_id": component_id,
            "author": "Example Author",
            "asset_page": "https://www.pexels.com/video/101",
            "job_path": f"source/{component_id}.png",
            "license_snapshot": f"source/{component_id}.license.json",
            "downloaded_at": "2026-08-31T12:00:00Z",
            "sha256": sha256,
        }
    if kind == "code_generated":
        return {
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "render.py",
            "producer_version": "approved-version",
            "brief_sha256": "4" * 64,
            "invocation_record": {"argv": ["python3", "render.py"], "exit_code": 0},
            "primary_renderer": "HyperFrames",
            "renderer_version": "approved-renderer",
            "template_origin": "custom_fallback",
            "template_id": "compositor-fixture",
            "template_version": "1",
            "verification_id": "7" * 64,
            "adaptation_level": "structural",
            "source_entrypoint": "templates/compositor-fixture.html",
            "source_sha256": "8" * 64,
            "sample_sha256": "9" * 64,
            "semantic_families": ["explanation"],
            "capacity": {"min_units": 1, "max_units": 7},
        }
    if kind == "ai_generated":
        return {
            "provider": "Example AI",
            "model": "image-model-v1",
            "endpoint_id": "image-generation",
            "prompt_sha256": "5" * 64,
            "generation_id": component_id,
            "sha256": sha256,
        }
    raise AssertionError(kind)


def _component(
    component_id: str,
    kind: str,
    sha256: str,
    *,
    window: dict[str, object],
    alpha: bool,
) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": (
            "annotation"
            if window["layout_slot"] in {"annotation", "lower-third"}
            else "overlay"
            if window["layout_slot"] in {"overlay", "main_overlay"}
            else "inset"
            if window["layout_slot"] == "inset"
            else "base"
        ),
        "executor": f"approved:{kind}",
        "media_type": "animation" if kind == "code_generated" else "image",
        "render_window": window,
        "artifact_contract": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "alpha": alpha,
        },
        **_binding(kind, component_id, sha256),
    }


def _recipe(components: list[dict[str, object]], *, source_sha256=_sha256_bytes(b"fixture-aroll")) -> dict[str, object]:
    mode = "single" if len(components) == 1 else "hybrid"
    base_ids = [
        component["component_id"]
        for component in components
        if component["layer_role"] == "base"
    ]
    recipe = {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 7,
        "mode": mode,
        "composition": {
            "family": "single_full_frame" if mode == "single" else "evidence_with_data_overlay",
            "presenter_mode": "bottom_window",
            "avatar": avatar_fixture(source_sha256=source_sha256),
            "reading_order": [component["component_id"] for component in components],
            "component_dependencies": [
                {
                    "component_id": component["component_id"],
                    "depends_on": base_ids[:1],
                }
                for component in components
                if component["layer_role"] == "annotation"
            ],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }
    return visual_strategy.validate_shot_recipe_v2(recipe)


def _segment(recipe: dict[str, object]) -> dict[str, object]:
    intent = {
        "segment_id": "seg-001",
        "statement": "Explain the approved idea with the approved components.",
        "semantic_goals": ["explain"],
        "claims": [
            {
                "type": "concept",
                "value": "The components share one visual explanation.",
                "verification_required": False,
            }
        ],
        "entities": [],
        "relations": [],
        "requirements": {
            "verifiability": "medium",
            "realism": "medium",
            "abstraction": "medium",
            "product_specificity": "low",
            "emotional_intensity": "low",
        },
        "presenter_presence": "allowed",
    }
    strategy = visual_strategy.validate_visual_strategy(
        intent,
        {
            "schema_version": 1,
            "segment_id": "seg-001",
            "mode": recipe["mode"],
            "rationale": "The approved layers share one deterministic composition.",
            "components": [
                {
                    "component_id": component["component_id"],
                    "kind": component["kind"],
                    "semantic_role": component["semantic_role"],
                    "layer_role": component["layer_role"],
                    "media_type": component["media_type"],
                    "layout_slot": component["render_window"]["layout_slot"],
                    "brief": f"Render {component['component_id']} in its approved layer.",
                }
                for component in recipe["components"]
            ],
            "composition": recipe["composition"],
        },
    )
    return {
        "segment_id": "seg-001",
        "start": 0.0,
        "end": 1.0,
        "visible_text": [],
        "visual_strategy": strategy,
        "shot_recipe": recipe,
    }


def _arroll_segment() -> dict[str, object]:
    composition = {
        "family": "no_broll",
        "presenter_mode": "full_frame",
        "reading_order": [],
        "component_dependencies": [],
    }
    return {
        "segment_id": "seg-001",
        "start": 0.0,
        "end": 1.0,
        "visible_text": [],
        "visual_strategy": {
            "schema_version": 1,
            "segment_id": "seg-001",
            "mode": "none",
            "rationale": "Keep the approved presenter footage for this segment.",
            "components": [],
            "composition": composition,
        },
        "shot_recipe": {
            "schema_version": 2,
            "segment_id": "seg-001",
            "strategy_revision": 7,
            "mode": "none",
            "composition": composition,
            "canvas": {"width": 1080, "height": 1920, "fps": 24},
            "components": [],
            "final_compositor": "ffmpeg",
        },
    }


def _probe(*, alpha: bool) -> dict[str, object]:
    return {
        "media_type": "image",
        "container": "png",
        "codec": "png",
        "pixel_format": "rgba" if alpha else "rgb24",
        "alpha": alpha,
        "width": 1080,
        "height": 1920,
        "fps": None,
        "frame_count": 1,
        "duration": None,
    }


def _artifact(
    job: _Job,
    recipe: dict[str, object],
    component: dict[str, object],
    path: Path,
    *,
    alpha: bool,
) -> broll_component_executor.ComponentArtifact:
    component_id = str(component["component_id"])
    input_sha = _sha256_bytes(
        _canonical({"recipe": recipe, "component_id": component_id})
    )
    evidence: dict[str, object] = {
        "output_job_path": path.relative_to(job.job_dir).as_posix(),
        "output_sha256": _sha256_file(path),
    }
    if component["kind"] == "code_generated":
        evidence["primary_renderer"] = component["primary_renderer"]
    return broll_component_executor.ComponentArtifact(
        schema_version=1,
        status="success",
        job_id=job.job_id,
        segment_id="seg-001",
        component_id=component_id,
        kind=str(component["kind"]),
        strategy_revision=7,
        media_type="image",
        render_window=component["render_window"],
        z_index=int(component["render_window"]["z_index"]),
        layout_slot=str(component["render_window"]["layout_slot"]),
        opacity=float(component["render_window"]["opacity"]),
        safe_zone=component["render_window"]["safe_zone"],
        artifact_contract=component["artifact_contract"],
        source_media_type=str(component["media_type"]),
        artifact_media_type="image",
        media_probe=_probe(alpha=alpha),
        input_sha256=input_sha,
        job_path=path.relative_to(job.job_dir).as_posix(),
        byte_count=path.stat().st_size,
        output_sha256=_sha256_file(path),
        invocation_evidence=evidence,
        qa={"passed": True, "checks": ["fixture"]},
        error_code=None,
    )


def _output_probe(frames: int = 24) -> dict[str, object]:
    return {
        "width": 1080,
        "height": 1920,
        "r_frame_rate": "24/1",
        "nb_read_frames": str(frames),
        "duration": frames / 24,
        "codec_name": "h264",
        "pix_fmt": "yuv420p",
    }


class SegmentRenderComponentTests(unittest.TestCase):
    def test_keyframe_moments_are_bounded_by_the_last_real_frame(self) -> None:
        self.assertEqual(
            segment_render._keyframe_moments(1),
            {"entry": 0.0, "hold": 0.0, "exit": 0.0},
        )
        self.assertEqual(
            segment_render._keyframe_moments(2),
            {"entry": 1 / 48, "hold": 1 / 24, "exit": 1 / 24},
        )
        self.assertEqual(
            segment_render._keyframe_moments(24),
            {"entry": 0.25, "hold": 0.5, "exit": 0.75},
        )

    def test_public_exports_include_aroll_render_and_strict_replay(self) -> None:
        self.assertEqual(
            segment_render.__all__,
            [
                "FPS",
                "WIDTH",
                "HEIGHT",
                "RENDERER_CONTRACT_VERSION",
                "RenderedSegment",
                "SegmentRenderError",
                "assemble_visual_track",
                "build_filter_graph",
                "expected_frames",
                "generation_identity",
                "load_rendered_segment_replay",
                "render_arroll_segment",
                "render_segment_video",
            ],
        )
        self.assertFalse(hasattr(segment_render, "resolve_runtime"))
        self.assertFalse(hasattr(segment_render, "DEFAULT_HYPERFRAMES_RUNTIME"))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.job = _Job(self.root)
        (self.job.job_dir / "source").mkdir()
        self.output_dir = self.job.job_dir / "rendered-segments"
        self.arroll = self.job.job_dir / "source/arroll.mp4"
        self.arroll.write_bytes(b"fixture-aroll")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _render(self, *args: object, **kwargs: object):
        kwargs.setdefault("arroll_sha256", _sha256_file(self.arroll))
        kwargs.setdefault("arroll_bytes", self.arroll.stat().st_size)
        return segment_render.render_segment_video(*args, **kwargs)

    def _single_fixture(self) -> tuple[dict[str, object], tuple[broll_component_executor.ComponentArtifact, ...]]:
        path = self.job.job_dir / "source/primary.png"
        path.write_bytes(b"approved-image")
        component = _component(
            "primary",
            "local_material",
            _sha256_file(path),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        recipe = _recipe([component], source_sha256=_sha256_file(self.arroll))
        return _segment(recipe), (
            _artifact(self.job, recipe, component, path, alpha=False),
        )

    def _hybrid_fixture(self) -> tuple[dict[str, object], tuple[broll_component_executor.ComponentArtifact, ...]]:
        base_path = self.job.job_dir / "source/base.png"
        overlay_path = self.job.job_dir / "source/overlay.png"
        base_path.write_bytes(b"base-image")
        overlay_path.write_bytes(b"overlay-image")
        base = _component(
            "base",
            "official_material",
            _sha256_file(base_path),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        overlay = _component(
            "overlay",
            "code_generated",
            _sha256_file(overlay_path),
            window=_window(
                start=8,
                end=16,
                z_index=10,
                slot="annotation",
                opacity=0.75,
            ),
            alpha=True,
        )
        recipe = _recipe([base, overlay], source_sha256=_sha256_file(self.arroll))
        return _segment(recipe), (
            _artifact(self.job, recipe, base, base_path, alpha=False),
            _artifact(self.job, recipe, overlay, overlay_path, alpha=True),
        )

    def _publish_fixture(self):
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(f"frame:{timestamp:.6f}".encode())

        result = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        return segment, artifacts, result, runner, extract

    def test_render_entry_accepts_only_component_artifacts(self) -> None:
        signature = inspect.signature(segment_render.render_segment_video)
        self.assertIn("artifacts", signature.parameters)
        self.assertIn("arroll_sha256", signature.parameters)
        self.assertIn("arroll_bytes", signature.parameters)
        for removed in ("runtime", "renderer", "media"):
            self.assertNotIn(removed, signature.parameters)

        segment, artifacts = self._single_fixture()
        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                tuple(dict(artifact) for artifact in artifacts),
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                arroll_sha256=_sha256_file(self.arroll),
                arroll_bytes=self.arroll.stat().st_size,
            )

    def test_malformed_composition_components_use_contract_errors(self) -> None:
        composition = {
            "family": "single_full_frame",
            "presenter_mode": "hidden",
            "reading_order": ["primary"],
            "component_dependencies": [],
        }
        for components in (None, {}, [None], ["primary"], ({},)):
            with self.subTest(components=components), self.assertRaises(
                visual_strategy.VisualStrategyError
            ):
                visual_strategy.validate_composition_contract(
                    composition, components, "single"
                )

        segment, artifacts = self._single_fixture()
        segment["visual_strategy"]["components"] = [None]
        with self.assertRaises(segment_render.SegmentRenderError):
            segment_render._prepare_render(self.job, segment, artifacts)

    def test_arroll_approval_and_job_output_path_are_checked_before_runner(self) -> None:
        segment, artifacts = self._single_fixture()
        invalid_cases = (
            {"arroll_sha256": "0" * 64, "arroll_bytes": self.arroll.stat().st_size},
            {
                "arroll_sha256": _sha256_file(self.arroll),
                "arroll_bytes": self.arroll.stat().st_size + 1,
            },
        )
        for approval in invalid_cases:
            runner = mock.Mock()
            with self.subTest(approval=approval), self.assertRaises(
                segment_render.SegmentRenderError
            ):
                segment_render.render_segment_video(
                    self.job,
                    segment,
                    artifacts,
                    output_dir=self.output_dir,
                    visual_plan_sha256="a" * 64,
                    arroll_source=self.arroll,
                    ffmpeg_runner=runner,
                    **approval,
                )
            runner.assert_not_called()

        runner = mock.Mock()
        with self.assertRaisesRegex(
            segment_render.SegmentRenderError, "output directory must be within the current Job"
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.root / "outside-job",
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
            )
        runner.assert_not_called()

    def test_arroll_bytes_are_part_of_identity_manifest_and_replay_validation(self) -> None:
        segment, artifacts, rendered, _runner, extract = self._publish_fixture()
        manifest_path = self.output_dir / "seg-001/segment-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["arroll_job_path"], "source/arroll.mp4")
        self.assertEqual(manifest["arroll_sha256"], _sha256_file(self.arroll))
        self.assertEqual(manifest["arroll_bytes"], self.arroll.stat().st_size)
        self.assertEqual(rendered.arroll_sha256, manifest["arroll_sha256"])

        self.arroll.write_bytes(b"changed-aroll")
        runner = mock.Mock()
        with self.assertRaises(segment_render.SegmentRenderError):
            segment_render.render_segment_video(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                arroll_sha256=manifest["arroll_sha256"],
                arroll_bytes=manifest["arroll_bytes"],
                ffmpeg_runner=runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        runner.assert_not_called()

    def test_filter_graph_uses_exact_windows_stable_layers_and_contained_layout(self) -> None:
        segment, artifacts = self._hybrid_fixture()
        graph = segment_render.build_filter_graph(
            segment["shot_recipe"], artifacts, frames=24
        )
        self.assertIn("between(n,0,23)", graph)
        self.assertIn("between(n,8,15)", graph)
        self.assertIn("force_original_aspect_ratio=decrease", graph)
        self.assertIn("gblur", graph)
        self.assertIn("colorchannelmixer=aa=0.750000", graph)
        self.assertNotIn("[component_0_source]crop=", graph)
        self.assertNotIn("[component_1_source]crop=", graph)
        self.assertLess(graph.index("component_0"), graph.index("component_1"))

    def test_renderer_matches_strategy_components_by_approved_reading_order(self) -> None:
        segment, artifacts = self._hybrid_fixture()
        segment["visual_strategy"]["components"] = list(
            reversed(segment["visual_strategy"]["components"])
        )
        prepared = segment_render._prepare_render(self.job, segment, artifacts)
        self.assertEqual(
            [component["component_id"] for component in prepared.recipe["components"]],
            segment["visual_strategy"]["composition"]["reading_order"],
        )

    def test_presenter_mode_controls_the_final_aroll_layer(self) -> None:
        segment, artifacts = self._single_fixture()
        bottom_graph = segment_render.build_filter_graph(
            segment["shot_recipe"], artifacts, frames=24
        )
        self.assertIn("[presenter]", bottom_graph)
        self.assertIn("overlay=768:1400", bottom_graph)
        self.assertGreater(bottom_graph.index("[presenter]"), bottom_graph.index("component_0"))

        hidden_recipe = copy.deepcopy(segment["shot_recipe"])
        hidden_recipe["composition"]["presenter_mode"] = "hidden"
        hidden_recipe["composition"].pop("avatar")
        hidden_recipe = visual_strategy.validate_shot_recipe_v2(hidden_recipe)
        hidden_graph = segment_render.build_filter_graph(
            hidden_recipe, artifacts, frames=24
        )
        self.assertNotIn("[presenter]", hidden_graph)
        self.assertNotIn("[0:v]fps=24", hidden_graph)

    def test_annotation_dependency_requires_a_shared_base_frame_window(self) -> None:
        segment, artifacts = self._hybrid_fixture()
        recipe = segment["shot_recipe"]
        annotation = recipe["components"][1]
        annotation["render_window"] = {
            **annotation["render_window"],
            "start_frame": 0,
            "end_frame": 8,
        }
        base = recipe["components"][0]
        base["render_window"] = {
            **base["render_window"],
            "start_frame": 8,
            "end_frame": 24,
        }
        with self.assertRaises(visual_strategy.VisualStrategyError):
            visual_strategy.validate_shot_recipe_v2(recipe)

    def test_decorative_full_frame_background_may_fill_the_canvas(self) -> None:
        segment, artifacts = self._single_fixture()
        artifact = replace(
            artifacts[0],
            safe_zone={"top": 0, "bottom": 0, "left": 0, "right": 0},
            render_window={
                **artifacts[0].render_window,
                "safe_zone": {"top": 0, "bottom": 0, "left": 0, "right": 0},
            },
        )
        graph = segment_render.build_filter_graph(
            segment["shot_recipe"], (artifact,), frames=24
        )
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=decrease", graph)
        self.assertIn("scale=1080:1920", graph)
        self.assertIn("gblur", graph)

    def test_unsupported_layout_and_soft_safe_overlap_are_rejected(self) -> None:
        segment, artifacts = self._single_fixture()
        recipe = segment["shot_recipe"]
        component = recipe["components"][0]
        cases = (
            {**component["render_window"], "layout_slot": "center_crop"},
            {
                **component["render_window"],
                "safe_zone": {
                    **component["render_window"]["safe_zone"],
                    "bottom": 100,
                },
            },
        )
        for window in cases:
            with self.subTest(window=window):
                changed = replace(
                    artifacts[0],
                    render_window=window,
                    layout_slot=str(window["layout_slot"]),
                    safe_zone=window["safe_zone"],
                )
                with self.assertRaises(segment_render.SegmentRenderError):
                    segment_render.build_filter_graph(recipe, (changed,), frames=24)

    def test_artifact_bindings_probe_hash_and_bytes_are_checked_before_runner(self) -> None:
        segment, artifacts = self._single_fixture()
        invalid = (
            replace(artifacts[0], job_id="another-job"),
            replace(artifacts[0], segment_id="seg-002"),
            replace(artifacts[0], strategy_revision=8),
            replace(artifacts[0], output_sha256="0" * 64),
            replace(artifacts[0], byte_count=artifacts[0].byte_count + 1),
            replace(artifacts[0], media_probe={**artifacts[0].media_probe, "width": 720}),
        )
        for artifact in invalid:
            with self.subTest(component_id=artifact.component_id):
                runner = mock.Mock()
                with self.assertRaises(segment_render.SegmentRenderError):
                    self._render(
                        self.job,
                        segment,
                        (artifact,),
                        output_dir=self.output_dir,
                        visual_plan_sha256="a" * 64,
                        arroll_source=self.arroll,
                        ffmpeg_runner=runner,
                    )
                runner.assert_not_called()
                self.assertFalse((self.output_dir / "seg-001").exists())

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_real_720p_ai_video_component_keeps_1080p_output_canvas(self) -> None:
        source = self.job.job_dir / "source/primary.mp4"
        for path, size, color in (
            (source, "720x1280", "0x2050e0"),
            (self.arroll, "1080x1920", "0x505050"),
        ):
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d=1",
                    "-frames:v", "24", "-an", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-y", str(path),
                ],
                check=True,
                capture_output=True,
            )
        component = _component(
            "primary",
            "ai_generated",
            _sha256_file(source),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        component["media_type"] = "video"
        component["artifact_contract"] = {
            "width": 720, "height": 1280, "fps": 24, "alpha": False
        }
        recipe = _recipe([component], source_sha256=_sha256_file(self.arroll))
        artifact = replace(
            _artifact(self.job, recipe, component, source, alpha=False),
            media_type="video",
            artifact_media_type="video",
            media_probe={
                "media_type": "video", "container": "mp4", "codec": "h264",
                "pixel_format": "yuv420p", "alpha": False, "width": 720,
                "height": 1280, "fps": 24, "frame_count": 24, "duration": 1.0,
            },
        )
        segment = _segment(recipe)
        graph = segment_render.build_filter_graph(recipe, (artifact,), frames=24)
        self.assertIn("scale=1080:1920:flags=lanczos", graph)
        self.assertIn("[presenter]", graph)

        rendered = self._render(
            self.job, segment, (artifact,), output_dir=self.output_dir,
            visual_plan_sha256="a" * 64, arroll_source=self.arroll,
        )
        self.assertEqual(rendered.output_probe["width"], 1080)
        self.assertEqual(rendered.output_probe["height"], 1920)
        self.assertTrue(segment_render._probe_matches(
            segment_render._default_probe(Path(rendered.video_path)), 24
        ))

    def test_runner_receives_private_snapshots_and_publication_has_no_work_files(self) -> None:
        segment, artifacts = self._hybrid_fixture()
        observed_inputs: list[Path] = []

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            for index, argument in enumerate(command[:-1]):
                if argument == "-i":
                    observed_inputs.append(Path(command[index + 1]))
            artifact_inputs = observed_inputs[1:]
            self.assertEqual(len(artifact_inputs), 2)
            for snapshot, artifact in zip(artifact_inputs, artifacts):
                self.assertIn(".seg-001.stage-", str(snapshot))
                self.assertNotEqual(snapshot, self.job.job_dir / artifact.job_path)
                self.assertEqual(_sha256_file(snapshot), artifact.output_sha256)
            Path(command[-1]).write_bytes(b"rendered-video")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(f"frame:{timestamp:.6f}".encode())

        rendered = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )

        target = self.output_dir / "seg-001"
        self.assertEqual(rendered.frames, 24)
        self.assertEqual(rendered.composition_family, "evidence_with_data_overlay")
        self.assertFalse((target / "inputs").exists())
        self.assertTrue((target / "segment.mp4").is_file())
        self.assertTrue((target / "segment-manifest.json").is_file())

    def test_changed_source_and_probe_time_output_change_leave_no_partial_result(self) -> None:
        segment, artifacts = self._single_fixture()
        source = self.job.job_dir / artifacts[0].job_path
        source.write_bytes(b"changed-before-render")
        runner = mock.Mock()
        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
            )
        runner.assert_not_called()

        segment, artifacts = self._single_fixture()

        def create_output(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"rendered-video")

        def changing_probe(path: Path) -> dict[str, object]:
            path.write_bytes(b"changed-after-probe-start")
            return _output_probe()

        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=create_output,
                probe=changing_probe,
            )
        self.assertFalse((self.output_dir / "seg-001").exists())
        self.assertEqual(list(self.output_dir.glob(".seg-001.stage-*")), [])

    def test_probe_and_keyframe_failures_are_stable_and_output_stays_unchanged(self) -> None:
        segment, artifacts = self._single_fixture()

        def create_output(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"rendered-video")

        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=create_output,
                probe=mock.Mock(side_effect=ValueError("invalid probe")),
            )
        self.assertFalse((self.output_dir / "seg-001").exists())

        def changing_extractor(video: Path, _timestamp: float, output: Path) -> None:
            video.write_bytes(b"changed-during-keyframes")
            output.write_bytes(b"frame")

        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=create_output,
                probe=lambda _path: _output_probe(),
                frame_extractor=changing_extractor,
            )
        self.assertFalse((self.output_dir / "seg-001").exists())
        self.assertEqual(list(self.output_dir.glob(".seg-001.stage-*")), [])

    def test_runner_failures_are_stable_and_leave_no_partial_result(self) -> None:
        segment, artifacts = self._single_fixture()
        def missing_output(_command: tuple[str, ...], _timeout: float) -> None:
            return None

        def partial_output(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"partial")
            raise OSError("write stopped")

        runners = (
            mock.Mock(side_effect=OSError("unavailable")),
            mock.Mock(side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])),
            mock.Mock(side_effect=subprocess.TimeoutExpired(["ffmpeg"], 1.0)),
            missing_output,
            partial_output,
        )
        for runner in runners:
            with self.subTest(runner=getattr(runner, "__name__", type(runner).__name__)):
                with self.assertRaisesRegex(
                    segment_render.SegmentRenderError, "component composition failed"
                ):
                    self._render(
                        self.job,
                        segment,
                        artifacts,
                        output_dir=self.output_dir,
                        visual_plan_sha256="a" * 64,
                        arroll_source=self.arroll,
                        ffmpeg_runner=runner,
                    )
                self.assertFalse((self.output_dir / "seg-001").exists())
                self.assertEqual(list(self.output_dir.glob(".seg-001.stage-*")), [])

    def test_process_termination_confirms_exit_or_preserves_stage(self) -> None:
        class Process:
            def __init__(self, *, direct_stops: bool) -> None:
                self.pid = 1234
                self.returncode = None
                self.group_alive = True
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.direct_stops = direct_stops
                self.terminate_calls = 0
                self.kill_calls = 0

            def poll(self):
                return self.returncode

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(["ffmpeg"], timeout)

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired(["ffmpeg"], timeout)
                return self.returncode

            def terminate(self):
                self.terminate_calls += 1
                if self.direct_stops:
                    self.returncode = -15
                    self.group_alive = False

            def kill(self):
                self.kill_calls += 1
                if self.direct_stops:
                    self.returncode = -9
                    self.group_alive = False

        def group_call(process: Process):
            def call(_pgrp: int, group_signal: int) -> None:
                if group_signal == 0 and not process.group_alive:
                    raise ProcessLookupError

            return call

        stopped = Process(direct_stops=True)
        with mock.patch.object(
            segment_render.os, "killpg", side_effect=group_call(stopped)
        ):
            segment_render._terminate_process(stopped)
        self.assertIsNotNone(stopped.poll())
        self.assertEqual(stopped.terminate_calls, 1)

        segment, artifacts = self._single_fixture()
        stuck = Process(direct_stops=False)
        with mock.patch.object(segment_render.subprocess, "Popen", return_value=stuck), mock.patch.object(
            segment_render.os, "killpg", side_effect=group_call(stuck)
        ):
            with self.assertRaisesRegex(
                segment_render.SegmentRenderError, "FFmpeg process did not stop"
            ):
                self._render(
                    self.job,
                    segment,
                    artifacts,
                    output_dir=self.output_dir,
                    visual_plan_sha256="a" * 64,
                    arroll_source=self.arroll,
                )
        self.assertIsNone(stuck.poll())
        retained = list(self.output_dir.glob(".seg-001.stage-*"))
        self.assertEqual(len(retained), 1)
        journal_path = self.output_dir / ".seg-001.publication-journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(journal["state"], "exit_unconfirmed")
        self.assertEqual(journal["process_identity"], {"pid": 1234, "pgrp": 1234})

        runner = mock.Mock(side_effect=AssertionError("must not run"))
        with mock.patch.object(
            segment_render, "_process_identity_exists", return_value=True
        ), self.assertRaisesRegex(
            segment_render.SegmentRenderError, "process exit is not confirmed"
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="b" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
            )
        runner.assert_not_called()
        self.assertTrue(retained[0].exists())

        def completed_runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        with mock.patch.object(
            segment_render, "_process_identity_exists", return_value=False
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="b" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=completed_runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        self.assertFalse(retained[0].exists())
        self.assertFalse(journal_path.exists())

    def test_aroll_entry_uses_the_same_identity_manifest_and_atomic_replay(self) -> None:
        segment = _arroll_segment()
        calls: list[tuple[str, ...]] = []

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            calls.append(command)
            Path(command[-1]).write_bytes(b"approved-aroll-segment")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(f"frame:{timestamp:.6f}".encode())

        kwargs = {
            "output_dir": self.output_dir,
            "visual_plan_sha256": "a" * 64,
            "arroll_source": self.arroll,
            "arroll_sha256": _sha256_file(self.arroll),
            "arroll_bytes": self.arroll.stat().st_size,
            "ffmpeg_runner": runner,
            "probe": lambda _path: _output_probe(),
            "frame_extractor": extract,
        }
        first = segment_render.render_arroll_segment(self.job, segment, **kwargs)
        second = segment_render.render_arroll_segment(self.job, segment, **kwargs)

        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)
        self.assertEqual(first.composition_family, "no_broll")
        self.assertEqual(first.composition, segment["shot_recipe"]["composition"])
        self.assertEqual(first.component_artifacts, [])
        self.assertEqual(first.arroll_job_path, "source/arroll.mp4")
        self.assertEqual(first.arroll_sha256, _sha256_file(self.arroll))
        self.assertEqual(first.arroll_bytes, self.arroll.stat().st_size)
        self.assertIn("[0:v]fps=24", calls[0][calls[0].index("-filter_complex") + 1])
        manifest = json.loads(
            (self.output_dir / "seg-001/segment-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest, asdict(first))

    def test_public_replay_validator_applies_the_complete_render_contract(self) -> None:
        segment, artifacts, rendered, _runner, _extract = self._publish_fixture()
        target = self.output_dir / "seg-001"
        manifest_path = target / "segment-manifest.json"
        original = manifest_path.read_bytes()

        def replay(
            *,
            selected_segment: dict[str, object] = segment,
            value: object = asdict(rendered),
        ) -> segment_render.RenderedSegment:
            return segment_render.load_rendered_segment_replay(
                self.job,
                selected_segment,
                value,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                arroll_sha256=_sha256_file(self.arroll),
                arroll_bytes=self.arroll.stat().st_size,
                probe=lambda _path: _output_probe(),
            )

        self.assertEqual(replay(), rendered)
        probe_process = mock.Mock(
            side_effect=AssertionError("replay must use the recorded probe")
        )
        with mock.patch.object(segment_render.subprocess, "run", probe_process):
            self.assertEqual(
                segment_render.load_rendered_segment_replay(
                    self.job,
                    segment,
                    asdict(rendered),
                    output_dir=self.output_dir,
                    visual_plan_sha256="a" * 64,
                    arroll_source=self.arroll,
                    arroll_sha256=_sha256_file(self.arroll),
                    arroll_bytes=self.arroll.stat().st_size,
                ),
                rendered,
            )
        probe_process.assert_not_called()

        for field, value in (
            ("frames", rendered.frames + 1),
            ("output_probe", {**rendered.output_probe, "codec_name": "hevc"}),
            (
                "component_artifacts",
                [
                    {
                        **rendered.component_artifacts[0],
                        "semantic_role": "another-role",
                    }
                ],
            ),
        ):
            value_record = json.loads(original)
            value_record[field] = value
            manifest_path.write_text(
                json.dumps(
                    value_record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with self.subTest(field=field), self.assertRaises(
                segment_render.SegmentRenderError
            ):
                replay(value=value_record)
            manifest_path.write_bytes(original)

        value_record = json.loads(original)
        value_record["keyframes"]["entry"]["timestamp"] += 0.125
        manifest_path.write_text(
            json.dumps(
                value_record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(segment_render.SegmentRenderError):
            replay(value=value_record)
        manifest_path.write_bytes(original)

        changed_segment = copy.deepcopy(segment)
        changed_segment["shot_recipe"]["composition"]["reading_order"] = []
        with self.assertRaises(segment_render.SegmentRenderError):
            replay(selected_segment=changed_segment)

        extra = target / "extra.bin"
        extra.write_bytes(b"extra")
        with self.assertRaises(segment_render.SegmentRenderError):
            replay()
        extra.unlink()
        missing = target / "keyframes/exit.png"
        parked = target / "keyframes/exit.parked"
        os.replace(missing, parked)
        with self.assertRaises(segment_render.SegmentRenderError):
            replay()

    def test_new_render_without_an_injected_probe_still_runs_the_default_probe(
        self,
    ) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"new-render-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(f"frame:{timestamp:.6f}".encode())

        selected_probe = mock.Mock(return_value=_output_probe())
        with mock.patch.object(
            segment_render,
            "_default_probe",
            selected_probe,
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                frame_extractor=extract,
            )

        selected_probe.assert_called_once()

    def test_process_identity_tracks_the_recorded_group_after_pid_reuse(self) -> None:
        with mock.patch.object(segment_render.os, "getpgid", return_value=9002), mock.patch.object(
            segment_render.os,
            "killpg",
            side_effect=ProcessLookupError,
        ):
            self.assertFalse(segment_render._process_identity_exists(1234, 9001))
        with mock.patch.object(segment_render.os, "getpgid", return_value=9002), mock.patch.object(
            segment_render.os,
            "killpg",
            return_value=None,
        ):
            self.assertTrue(segment_render._process_identity_exists(1234, 9001))
        with mock.patch.object(segment_render.os, "getpgid", return_value=9001), mock.patch.object(
            segment_render.os,
            "killpg",
        ) as group_probe:
            self.assertTrue(segment_render._process_identity_exists(1234, 9001))
            group_probe.assert_not_called()

    def test_process_termination_waits_for_group_after_leader_exit(self) -> None:
        class ExitedLeader:
            pid = 1234
            returncode = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                raise AssertionError("exited leader must not receive terminate")

            def kill(self):
                raise AssertionError("exited leader must not receive kill")

        process = ExitedLeader()

        def persistent_group(pgrp: int, group_signal: int) -> None:
            self.assertEqual(pgrp, 1234)

        with mock.patch.object(segment_render.os, "getpgid", side_effect=ProcessLookupError), mock.patch.object(
            segment_render.os, "killpg", side_effect=persistent_group
        ), self.assertRaises(segment_render._PreserveStageError) as captured:
            segment_render._terminate_process(process)
        self.assertEqual((captured.exception.pid, captured.exception.pgrp), (1234, 1234))

    def test_successful_runner_settles_group_or_preserves_stage(self) -> None:
        class SuccessfulProcess:
            def __init__(self, *, group_stops: bool) -> None:
                self.pid = 1234
                self.returncode = 0
                self.group_alive = True
                self.group_stops = group_stops
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.group_signals: list[int] = []

            def communicate(self, timeout=None):
                return b"", b""

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                raise AssertionError("exited leader must not receive terminate")

            def kill(self):
                raise AssertionError("exited leader must not receive kill")

            def group_call(self, _pgrp: int, group_signal: int) -> None:
                if group_signal == 0:
                    if not self.group_alive:
                        raise ProcessLookupError
                    return
                self.group_signals.append(group_signal)
                if self.group_stops:
                    self.group_alive = False

        settled = SuccessfulProcess(group_stops=True)
        with mock.patch.object(
            segment_render.subprocess, "Popen", return_value=settled
        ), mock.patch.object(
            segment_render.os, "killpg", side_effect=settled.group_call
        ):
            segment_render._default_ffmpeg_runner(("ffmpeg",), 1.0)
        self.assertEqual(settled.group_signals, [signal.SIGTERM])
        self.assertFalse(settled.group_alive)

        segment, artifacts = self._single_fixture()
        retained = SuccessfulProcess(group_stops=False)

        def launch(command, **_kwargs):
            Path(command[-1]).write_bytes(b"stable-output")
            return retained

        probe = mock.Mock(side_effect=AssertionError("probe must not run"))
        with mock.patch.object(
            segment_render.subprocess, "Popen", side_effect=launch
        ), mock.patch.object(
            segment_render.os, "killpg", side_effect=retained.group_call
        ), self.assertRaisesRegex(
            segment_render.SegmentRenderError, "FFmpeg process did not stop"
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                probe=probe,
            )
        probe.assert_not_called()
        stages = list(self.output_dir.glob(".seg-001.stage-*"))
        self.assertEqual(len(stages), 1)
        journal = json.loads(
            (self.output_dir / ".seg-001.publication-journal.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(journal["state"], "exit_unconfirmed")
        self.assertEqual(journal["process_identity"], {"pid": 1234, "pgrp": 1234})
        self.assertFalse((self.output_dir / "seg-001").exists())

    def test_video_artifact_is_trimmed_without_image_looping(self) -> None:
        path = self.job.job_dir / "source/video.mp4"
        path.write_bytes(b"approved-video")
        component = _component(
            "video",
            "external_stock",
            _sha256_file(path),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        component["media_type"] = "video"
        component["job_path"] = "source/video.mp4"
        recipe = _recipe([component])
        image_artifact = _artifact(self.job, recipe, component, path, alpha=False)
        artifact = replace(
            image_artifact,
            media_type="video",
            artifact_media_type="video",
            media_probe={
                "media_type": "video",
                "container": "mp4",
                "codec": "h264",
                "pixel_format": "yuv420p",
                "alpha": False,
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "frame_count": 24,
                "duration": 1.0,
            },
        )
        observed: list[tuple[str, ...]] = []

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            observed.append(command)
            Path(command[-1]).write_bytes(b"rendered-video")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        self._render(
            self.job,
            _segment(recipe),
            (artifact,),
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        self.assertEqual(len(observed), 1)
        self.assertNotIn("-loop", observed[0])
        graph = observed[0][observed[0].index("-filter_complex") + 1]
        self.assertIn("trim=start_frame=0:end_frame=24", graph)

    def test_compositor_does_not_invoke_component_or_provider_producers(self) -> None:
        source = inspect.getsource(segment_render)
        self.assertNotIn("execute_component(", source)
        self.assertNotIn("search_stock", source)
        self.assertNotIn("download_to_staging", source)

    def test_same_inputs_replay_without_running_ffmpeg_again(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        first = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        no_second_run = mock.Mock(side_effect=AssertionError("must reuse output"))
        second = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=no_second_run,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        self.assertEqual(first, second)
        no_second_run.assert_not_called()

    def test_same_identity_concurrent_render_runs_once_then_exactly_replays(self) -> None:
        segment, artifacts = self._single_fixture()
        entered = threading.Event()
        release = threading.Event()
        runner_calls: list[tuple[str, ...]] = []
        results: list[object] = []
        failures: list[BaseException] = []

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            runner_calls.append(command)
            entered.set()
            self.assertTrue(release.wait(5))
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        def invoke() -> None:
            try:
                results.append(
                    self._render(
                        self.job,
                        segment,
                        artifacts,
                        output_dir=self.output_dir,
                        visual_plan_sha256="a" * 64,
                        arroll_source=self.arroll,
                        ffmpeg_runner=runner,
                        probe=lambda _path: _output_probe(),
                        frame_extractor=extract,
                    )
                )
            except BaseException as failure:
                failures.append(failure)

        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        self.assertTrue(entered.wait(5))
        second.start()
        release.set()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(runner_calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])

    def test_interrupted_probe_retry_cleans_owned_stage_and_keeps_unknown_stage(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        with self.assertRaises(KeyboardInterrupt):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=mock.Mock(side_effect=KeyboardInterrupt()),
            )
        owned = list(self.output_dir.glob(".seg-001.stage-*"))
        self.assertEqual(len(owned), 1)
        journal_path = self.output_dir / ".seg-001.publication-journal.json"
        transaction = json.loads(
            journal_path.read_text(encoding="utf-8")
        )
        self.assertEqual(transaction["state"], "complete")
        self.assertEqual(transaction["stage_name"], owned[0].name)
        self.assertEqual(
            transaction["stage_identity"]["ino"], owned[0].stat().st_ino
        )

        untracked_nonce = "f" * 32
        unknown = self.output_dir / f".seg-001.stage-{untracked_nonce}"
        unknown.mkdir()
        sentinel = unknown / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        (unknown / ".render-transaction.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "job_id": self.job.job_id,
                    "segment_id": "seg-001",
                    "generation_identity": transaction["generation_identity"],
                    "owner_nonce": untracked_nonce,
                    "state": "rendering",
                }
            ),
            encoding="utf-8",
        )

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        self.assertFalse(owned[0].exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(journal_path.exists())

    def test_publication_journal_recovers_before_and_after_directory_replace(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        actual_replace = segment_render.os.replace

        def interrupt_stage_replace(source: object, destination: object) -> None:
            if Path(source).name.startswith(".seg-001.stage-"):
                raise KeyboardInterrupt()
            actual_replace(source, destination)

        with mock.patch.object(
            segment_render.os, "replace", side_effect=interrupt_stage_replace
        ), self.assertRaises(KeyboardInterrupt):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        journal_path = self.output_dir / ".seg-001.publication-journal.json"
        before = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(before["state"], "publishing")
        self.assertTrue((self.output_dir / before["stage_name"]).is_dir())

        self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        shutil.rmtree(self.output_dir / "seg-001")

        actual_fsync_directory = segment_render._fsync_directory

        def interrupt_after_replace(path: Path) -> None:
            if Path(path) == self.output_dir:
                raise KeyboardInterrupt()
            actual_fsync_directory(path)

        with mock.patch.object(
            segment_render,
            "_fsync_directory",
            side_effect=interrupt_after_replace,
        ), self.assertRaises(KeyboardInterrupt):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        after = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(after["state"], "publishing")
        self.assertTrue((self.output_dir / "seg-001").is_dir())
        no_rerender = mock.Mock(side_effect=AssertionError("must replay published output"))
        self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=no_rerender,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        no_rerender.assert_not_called()
        self.assertFalse(journal_path.exists())

    def test_publication_recovery_requires_the_recorded_stage_identity(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        with self.assertRaises(KeyboardInterrupt):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=mock.Mock(side_effect=KeyboardInterrupt()),
            )
        journal_path = self.output_dir / ".seg-001.publication-journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        stage = self.output_dir / journal["stage_name"]
        parked = self.output_dir / ".parked-stage"
        os.replace(stage, parked)
        stage.mkdir()
        sentinel = stage / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        no_runner = mock.Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(
            segment_render.SegmentRenderError, "staging identity changed"
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=no_runner,
            )
        no_runner.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertTrue(parked.exists())

    def test_new_generation_recovers_only_the_recorded_incomplete_stage(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        with self.assertRaises(KeyboardInterrupt):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=mock.Mock(side_effect=KeyboardInterrupt()),
            )
        journal_path = self.output_dir / ".seg-001.publication-journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        old_stage = self.output_dir / journal["stage_name"]
        unknown = self.output_dir / f".seg-001.stage-{'e' * 32}"
        unknown.mkdir()
        sentinel = unknown / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        # A changed input, not a change elsewhere in the parent visual plan,
        # distinguishes a new segment generation under the segment-input contract.
        segment = {**segment, "start": segment["start"] + 1 / 24, "end": segment["end"] + 1 / 24}
        rendered = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="b" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        self.assertFalse(old_stage.exists())
        self.assertFalse(journal_path.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(rendered.generation_identity, json.loads(
            (self.output_dir / "seg-001/segment-manifest.json").read_text(encoding="utf-8")
        )["generation_identity"])

        no_runner = mock.Mock(side_effect=AssertionError("must not replace another generation"))
        replay = self._render(
            self.job, segment, artifacts, output_dir=self.output_dir,
            visual_plan_sha256="c" * 64, arroll_source=self.arroll,
            ffmpeg_runner=no_runner, probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        self.assertEqual(replay.generation_identity, rendered.generation_identity)
        segment = {**segment, "start": segment["start"] + 1 / 24, "end": segment["end"] + 1 / 24}
        with self.assertRaisesRegex(
            segment_render.SegmentRenderError, "another identity"
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="c" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=no_runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        no_runner.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_publication_syncs_keyframe_directory_before_stage(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        events: list[tuple[str, Path]] = []
        actual_fsync_file = segment_render._fsync_file
        actual_fsync_directory = segment_render._fsync_directory

        def record_file(path: Path) -> None:
            events.append(("file", Path(path)))
            actual_fsync_file(path)

        def record_directory(path: Path) -> None:
            events.append(("directory", Path(path)))
            actual_fsync_directory(path)

        with mock.patch.object(
            segment_render, "_fsync_file", side_effect=record_file
        ), mock.patch.object(
            segment_render, "_fsync_directory", side_effect=record_directory
        ):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=runner,
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )

        keyframe_files = [
            index
            for index, (kind, path) in enumerate(events)
            if kind == "file" and path.parent.name == "keyframes"
        ]
        keyframe_directory = next(
            index
            for index, (kind, path) in enumerate(events)
            if kind == "directory" and path.name == "keyframes"
        )
        stage_directory = next(
            index
            for index, (kind, path) in enumerate(events)
            if kind == "directory" and path.name.startswith(".seg-001.stage-")
        )
        self.assertEqual(len(keyframe_files), 3)
        self.assertLess(max(keyframe_files), keyframe_directory)
        self.assertLess(keyframe_directory, stage_directory)

    def test_replay_rejects_changed_manifest_component_records(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )
        manifest = self.output_dir / "seg-001/segment-manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            set(value["component_artifacts"][0]),
            set(broll_component_executor.ComponentArtifact.__dataclass_fields__),
        )
        value["component_artifacts"][0]["kind"] = "ai_generated"
        manifest.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=mock.Mock(side_effect=AssertionError("must not run")),
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )

    def test_replay_rechecks_video_bytes_after_probe(self) -> None:
        segment, artifacts = self._single_fixture()

        def runner(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"stable-output")

        def extract(_video: Path, timestamp: float, output: Path) -> None:
            output.write_bytes(str(timestamp).encode())

        self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
            probe=lambda _path: _output_probe(),
            frame_extractor=extract,
        )

        def changing_probe(path: Path) -> dict[str, object]:
            path.write_bytes(b"changed-during-replay-probe")
            return _output_probe()

        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=mock.Mock(side_effect=AssertionError("must not run")),
                probe=changing_probe,
                frame_extractor=extract,
            )

    def test_replay_requires_exact_manifest_keyframes_and_formal_output_set(self) -> None:
        segment, artifacts, _rendered, _runner, extract = self._publish_fixture()
        target = self.output_dir / "seg-001"
        manifest_path = target / "segment-manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))

        def write(value: dict[str, object]) -> None:
            manifest_path.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )

        cases = []
        changed = json.loads(json.dumps(original))
        changed["segment_id"] = "seg-999"
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["unexpected"] = True
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["keyframes"]["extra"] = changed["keyframes"]["entry"]
        cases.append(changed)
        for field, value in (
            ("timestamp", original["keyframes"]["entry"]["timestamp"] + 0.1),
            ("path", str(target / "keyframes/other.png")),
            ("sha256", "0" * 64),
            ("bytes", original["keyframes"]["entry"]["bytes"] + 1),
        ):
            changed = json.loads(json.dumps(original))
            changed["keyframes"]["entry"][field] = value
            cases.append(changed)

        for changed in cases:
            write(changed)
            with self.subTest(change=changed), self.assertRaises(
                segment_render.SegmentRenderError
            ):
                self._render(
                    self.job,
                    segment,
                    artifacts,
                    output_dir=self.output_dir,
                    visual_plan_sha256="a" * 64,
                    arroll_source=self.arroll,
                    ffmpeg_runner=mock.Mock(side_effect=AssertionError("must not run")),
                    probe=lambda _path: _output_probe(),
                    frame_extractor=extract,
                )
            write(original)

        extra = target / "unexpected.bin"
        extra.write_bytes(b"unexpected")
        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=mock.Mock(side_effect=AssertionError("must not run")),
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )
        extra.unlink()
        (target / "keyframes/entry.png").write_bytes(b"changed-keyframe")
        with self.assertRaises(segment_render.SegmentRenderError):
            self._render(
                self.job,
                segment,
                artifacts,
                output_dir=self.output_dir,
                visual_plan_sha256="a" * 64,
                arroll_source=self.arroll,
                ffmpeg_runner=mock.Mock(side_effect=AssertionError("must not run")),
                probe=lambda _path: _output_probe(),
                frame_extractor=extract,
            )

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_real_two_layer_render_has_exact_frames_and_frame_window(self) -> None:
        base_path = self.job.job_dir / "source/base.png"
        overlay_path = self.job.job_dir / "source/overlay.png"
        Image.new("RGB", (1080, 1920), (220, 30, 30)).save(base_path)
        overlay_image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        ImageDraw.Draw(overlay_image).rectangle(
            (390, 810, 690, 1110), fill=(20, 60, 230, 255)
        )
        overlay_image.save(overlay_path)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x505050:s=1080x1920:r=24:d=1",
                "-frames:v",
                "24",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(self.arroll),
            ],
            check=True,
            capture_output=True,
        )
        base = _component(
            "base",
            "official_material",
            _sha256_file(base_path),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        overlay = _component(
            "overlay",
            "code_generated",
            _sha256_file(overlay_path),
            window=_window(start=8, end=16, z_index=10, slot="annotation"),
            alpha=True,
        )
        recipe = _recipe([base, overlay], source_sha256=_sha256_file(self.arroll))
        segment = _segment(recipe)
        artifacts = (
            _artifact(self.job, recipe, base, base_path, alpha=False),
            _artifact(self.job, recipe, overlay, overlay_path, alpha=True),
        )
        rendered = self._render(
            self.job,
            segment,
            artifacts,
            output_dir=self.output_dir,
            visual_plan_sha256="a" * 64,
            arroll_source=self.arroll,
        )
        probe = segment_render._default_probe(Path(rendered.video_path))
        self.assertTrue(segment_render._probe_matches(probe, 147))

        def pixel(
            timestamp: float,
            *,
            video_path: str = rendered.video_path,
            x: int = 540,
            y: int = 960,
        ) -> tuple[int, int, int]:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    video_path,
                    "-vf",
                    f"crop=2:2:{x}:{y},scale=1:1:flags=neighbor",
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            )
            return tuple(result.stdout[:3])

        before = pixel(0.15)
        during = pixel(0.50)
        during_clear_area = pixel(0.50, x=100, y=500)
        after = pixel(0.85)
        self.assertGreater(before[0], before[2])
        self.assertGreater(during[2], during[0])
        self.assertGreater(during_clear_area[0], during_clear_area[2])
        self.assertGreater(after[0], after[2])

        hidden_recipe = copy.deepcopy(recipe)
        hidden_recipe["composition"]["presenter_mode"] = "hidden"
        hidden_recipe["composition"].pop("avatar")
        hidden_recipe = visual_strategy.validate_shot_recipe_v2(hidden_recipe)
        hidden_artifacts = (
            _artifact(self.job, hidden_recipe, base, base_path, alpha=False),
            _artifact(self.job, hidden_recipe, overlay, overlay_path, alpha=True),
        )
        hidden = self._render(
            self.job,
            _segment(hidden_recipe),
            hidden_artifacts,
            output_dir=self.job.job_dir / "rendered-hidden",
            visual_plan_sha256="c" * 64,
            arroll_source=self.arroll,
        )
        bottom_presenter_pixel = pixel(0.5, x=900, y=1520)
        hidden_presenter_pixel = pixel(
            0.5, video_path=hidden.video_path, x=900, y=1520
        )
        self.assertNotEqual(bottom_presenter_pixel, hidden_presenter_pixel)
        self.assertLess(
            max(bottom_presenter_pixel) - min(bottom_presenter_pixel), 25
        )
        self.assertGreater(hidden_presenter_pixel[0], hidden_presenter_pixel[2])

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_real_horizontal_source_is_normalized_before_component_composition(self) -> None:
        source_path = self.job.job_dir / "source/horizontal.mp4"
        video_path = self.job.job_dir / "source/horizontal-normalized.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x2050e0:s=640x360:r=24:d=1",
                "-frames:v",
                "24",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(source_path),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(source_path),
                "-vf",
                (
                    "fps=24,scale=1080:1920:force_original_aspect_ratio=decrease:"
                    "flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
                ),
                "-frames:v",
                "24",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(video_path),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x505050:s=1080x1920:r=24:d=1",
                "-frames:v",
                "24",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(self.arroll),
            ],
            check=True,
            capture_output=True,
        )
        component = _component(
            "horizontal",
            "external_stock",
            _sha256_file(video_path),
            window=_window(start=0, end=24, z_index=0, slot="full_frame"),
            alpha=False,
        )
        component["media_type"] = "video"
        component["job_path"] = "source/horizontal-normalized.mp4"
        recipe = _recipe([component], source_sha256=_sha256_file(self.arroll))
        image_artifact = _artifact(
            self.job, recipe, component, video_path, alpha=False
        )
        artifact = replace(
            image_artifact,
            media_type="video",
            artifact_media_type="video",
            media_probe={
                "media_type": "video",
                "container": "mp4",
                "codec": "h264",
                "pixel_format": "yuv420p",
                "alpha": False,
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "frame_count": 24,
                "duration": 1.0,
            },
        )
        commands: list[tuple[str, ...]] = []

        def runner(command: tuple[str, ...], timeout: float) -> None:
            commands.append(command)
            segment_render._default_ffmpeg_runner(command, timeout)

        rendered = self._render(
            self.job,
            _segment(recipe),
            (artifact,),
            output_dir=self.output_dir,
            visual_plan_sha256="b" * 64,
            arroll_source=self.arroll,
            ffmpeg_runner=runner,
        )
        probe = segment_render._default_probe(Path(rendered.video_path))
        self.assertTrue(segment_render._probe_matches(probe, 24))
        self.assertEqual(len(commands), 1)
        self.assertNotIn("-loop", commands[0])
        graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("force_original_aspect_ratio=decrease", graph)
        self.assertNotIn("[component_0_source]crop=", graph)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_default_visual_track_concat_is_exact_silent_vertical_video(self) -> None:
        segment_paths = [self.job.job_dir / f"concat-{index}.mp4" for index in range(2)]
        frame_counts = (2, 145)
        colors = ("red", "blue")
        for index, (path, frame_count, color) in enumerate(
            zip(segment_paths, frame_counts, colors)
        ):
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostdin",
                    "-xerror",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s=1080x1920:r=24",
                    "-frames:v",
                    str(frame_count),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(path),
                ],
                check=True,
                capture_output=True,
            )
        rendered = [
            segment_render.RenderedSegment(
                segment_id=f"seg-00{index + 1}",
                video_path=str(path),
                video_sha256=_sha256_file(path),
                video_bytes=path.stat().st_size,
                frames=frame_counts[index],
                generation_identity=str(index) * 64,
                composition_family="single_full_frame",
                composition={},
                arroll_job_path="06-edit-structure/edited-aroll.mp4",
                arroll_sha256="a" * 64,
                arroll_bytes=1,
                component_artifacts=[],
                output_probe={},
                keyframes={},
            )
            for index, path in enumerate(segment_paths)
        ]

        output = self.job.job_dir / "visual-track.mp4"
        segment_render.assemble_visual_track(rendered, output)
        probe = segment_render._default_probe(output)
        self.assertTrue(segment_render._probe_matches(probe, 147))
        self.assertEqual((probe["width"], probe["height"]), (1080, 1920))
        self.assertEqual(probe["r_frame_rate"], "24/1")

        def pixel_framemd5(path: Path) -> list[str]:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-f",
                    "framemd5",
                    "-",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return [
                line.rsplit(",", 1)[1].strip()
                for line in result.stdout.splitlines()
                if line and not line.startswith("#")
            ]

        expected_hashes = pixel_framemd5(segment_paths[0]) + pixel_framemd5(
            segment_paths[1]
        )
        self.assertEqual(pixel_framemd5(output), expected_hashes)

        pts_probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=time_base:frame=pts",
                "-of", "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        pts_payload = json.loads(pts_probe.stdout)
        time_base = Fraction(pts_payload["streams"][0]["time_base"])
        pts = [Fraction(frame["pts"]) * time_base for frame in pts_payload["frames"]]
        self.assertEqual(len(pts), 147)
        self.assertEqual(
            pts,
            [Fraction(index, 24) for index in range(147)],
        )
        streams = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(streams, ["video"])


if __name__ == "__main__":
    unittest.main()

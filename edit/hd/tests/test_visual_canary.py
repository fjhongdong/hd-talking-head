from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from edit.hd.tests import test_broll_component_executor as executor_fixtures
from edit.hd.tests.test_visual_plan import binding, recipe, visual_intent, visual_strategy
from edit.hd.tools import (
    broll_component_executor,
    cover_direction,
    contract_artifacts,
    material_usage,
    state,
    stock_media,
    segment_render,
    visual_assets,
    visual_assets_v2,
    visual_canary,
    visual_plan,
)
from edit.v4.tools import prepare_official_sources


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _segment(identifier: str, start: float, kinds: tuple[str, ...]) -> dict[str, object]:
    candidates = {
        f"component-{index + 1}": [{
            "asset_id": f"asset-{index + 1}",
            "kind": kind,
            "semantic_match_score": 0.9,
            "quality_score": 0.8,
            "hard_gates": {
                "semantic_match": True,
                "factual_reliability": True,
                "native_vertical": True,
                "quality_readability": True,
            },
        }]
        for index, kind in enumerate(kinds)
        if kind in {"local_material", "official_material", "external_stock"}
    }
    return {
        "segment_id": identifier,
        "start": start,
        "end": start + 3.0,
        "content_item_ids": ["idea-01"],
        "visible_text": [],
        "visual_intent": visual_intent(identifier),
        "visual_strategy": visual_strategy(kinds, segment_id=identifier),
        "candidate_snapshots": candidates,
        "bindings": {
            f"component-{index + 1}": binding(kind, f"asset-{index + 1}")
            for index, kind in enumerate(kinds)
        },
        "shot_recipe": recipe(kinds, segment_id=identifier),
    }


def _plan(arroll_sha256: str) -> dict[str, object]:
    base = {
        "schema_version": 3,
        "content_analysis_sha256": "a" * 64,
        "edit_plan_sha256": "b" * 64,
        "timeline_map_sha256": "c" * 64,
        "edited_aroll_sha256": arroll_sha256,
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "duration": 12.0,
        "segments": [
            _segment("seg-011", 0.0, ("code_generated",)),
            _segment("seg-012", 3.0, ("external_stock",)),
            _segment("seg-013", 6.0, ("ai_generated",)),
            _segment("seg-014", 9.0, ()),
        ],
        "source_summary": {
            "code_generated": 1,
            "external_stock": 1,
            "ai_generated": 1,
        },
    }
    for segment in base["segments"]:
        for key in ("visual_strategy", "shot_recipe"):
            avatar = segment[key]["composition"].get("avatar")
            if avatar is not None:
                avatar["profile"]["source_sha256"] = arroll_sha256
    return {**base, "visual_plan_sha256": contract_artifacts.sha256_json(base)}


class VisualCanaryV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        source = self.root / "source.mp4"
        script = self.root / "script.md"
        source.write_bytes(b"source")
        script.write_text("测试文案", encoding="utf-8")
        self.job = state.create_job(self.root, source, script, profile="full-v2")
        for stage_id, relative in (
            ("inspect", "01-inspect/report.json"),
            ("content_analysis", "02-content-analysis/content-analysis.json"),
            ("cover_direction", "03-cover-direction/cover-direction.json"),
            ("cover", "04-cover/cover-report.json"),
            ("speech_cleanup", "05-speech-cleanup/word-transcript.json"),
        ):
            path = self.job.job_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            state.mark_ready(self.job, stage_id, (path,))
            state.approve(self.job, stage_id)

        edit_root = self.job.job_dir / "06-edit-structure"
        edit_root.mkdir(parents=True, exist_ok=True)
        edit_plan = edit_root / "edit-plan.json"
        timeline = edit_root / "timeline-map.json"
        self.arroll = edit_root / "edited-aroll.mp4"
        edit_plan.write_text("{}\n", encoding="utf-8")
        timeline.write_text("{}\n", encoding="utf-8")
        self.arroll.write_bytes(b"approved-edited-aroll")
        state.mark_ready(self.job, "edit_structure", (edit_plan, timeline, self.arroll))
        state.approve(self.job, "edit_structure")

        self.code_brief = b"approved code composition"
        self.code_output = b"code-video-output"
        self.stock_source = b"approved-stock-source"
        self.stock_output = b"stock-image-output"
        self.ai_output = b"ai-image-output"
        raw_plan = _plan(_sha256(self.arroll))
        code_binding = {
            **binding("code_generated", "asset-1"),
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "render.py",
            "producer_version": "approved-version",
            "brief_sha256": hashlib.sha256(self.code_brief).hexdigest(),
            "invocation_record": {
                "argv": ["python", "render.py"],
                "exit_code": 0,
                "template_request": {"semantic_family": "explanation", "information_units": 3,
                                     "numeric_values": [], "numeric_scale": "not_applicable"},
            },
            "primary_renderer": "HyperFrames",
            "renderer_version": "approved-renderer",
        }
        code_segment = raw_plan["segments"][0]
        code_segment["bindings"]["component-1"] = code_binding
        code_segment["shot_recipe"]["components"][0].update(code_binding)

        stock_key = "a" * 64
        stock_binding = {
            "provider": "Pexels",
            "provider_asset_id": "101",
            "author": "Example Author",
            "asset_page": "https://www.pexels.com/video/101",
            "job_path": f"stock/{stock_key[:2]}/{stock_key}.mp4",
            "license_snapshot": f"stock/{stock_key[:2]}/{stock_key}.license.json",
            "downloaded_at": "2026-08-31T12:00:00Z",
            "sha256": hashlib.sha256(self.stock_source).hexdigest(),
        }
        stock_segment = raw_plan["segments"][1]
        stock_segment["bindings"]["component-1"] = stock_binding
        stock_segment["shot_recipe"]["components"][0].update(stock_binding)
        stock_segment["shot_recipe"]["components"][0]["media_type"] = "video"
        stock_segment["visual_strategy"]["components"][0]["media_type"] = "video"
        stock_segment["candidate_snapshots"]["component-1"][0]["asset_id"] = "101"

        ai_sha256 = hashlib.sha256(self.ai_output).hexdigest()
        ai_segment = raw_plan["segments"][2]
        ai_segment["bindings"]["component-1"]["sha256"] = ai_sha256
        ai_segment["shot_recipe"]["components"][0]["sha256"] = ai_sha256
        unsigned_plan = {
            key: value
            for key, value in raw_plan.items()
            if key != "visual_plan_sha256"
        }
        raw_plan["visual_plan_sha256"] = contract_artifacts.sha256_json(
            unsigned_plan
        )
        self.plan = visual_plan.validate_visual_plan(raw_plan)

        stock_component = self.plan["segments"][1]["shot_recipe"]["components"][0]
        stock_path = self.job.job_dir / str(stock_component["job_path"])
        stock_path.parent.mkdir(parents=True, exist_ok=True)
        stock_path.write_bytes(self.stock_source)
        executor_fixtures._write_stock_license(
            self.job,
            stock_component,
            self.stock_source,
        )
        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        review_path = self.job.job_dir / "07-visual-direction/visual-routing.md"
        contract_artifacts.write_json_artifact(plan_path, self.plan)
        contract_artifacts.write_text_artifact(review_path, "# review\n")
        state.mark_ready(self.job, "visual_direction", (plan_path, review_path))
        state.approve(self.job, "visual_direction")

        self.execution_requests: list[
            broll_component_executor.ComponentExecutionRequest
        ] = []
        self.adapter_calls: dict[
            str,
            list[broll_component_executor.AdapterContext],
        ] = {"code_generated": [], "external_stock": [], "ai_generated": []}
        self.ffmpeg_calls: list[tuple[str, ...]] = []
        self.component_adapters = self._component_adapters()
        native_process = broll_component_executor._run_reference_process

        def observe_process(*args: object) -> object:
            result = native_process(*args)
            self.adapter_calls["code_generated"].append(args[-1])
            return result

        observer = mock.patch.object(broll_component_executor, "_run_reference_process", side_effect=observe_process)
        observer.start()
        self.addCleanup(observer.stop)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _component_adapters(self) -> dict[str, object]:
        def media_probe(
            _path: Path,
            media_type: str,
            contract: object,
        ) -> dict[str, object]:
            alpha = bool(contract["alpha"])
            if media_type == "image":
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
            return {
                "media_type": "video",
                "container": "mov" if alpha else "mp4",
                "codec": "prores_ks" if alpha else "h264",
                "pixel_format": "yuva444p10le" if alpha else "yuv420p",
                "alpha": alpha,
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "frame_count": 72,
                "duration": 3.0,
            }

        dependency_root = self.root / "html-video-reference"
        dependency_root.mkdir()
        entrypoint = dependency_root / "render.py"
        entrypoint.write_text(
            "from pathlib import Path\nimport argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args()\n"
            f"assert Path(a.brief).read_bytes() == {self.code_brief!r}\n"
            f"Path(a.output).write_bytes({self.code_output!r})\n",
            encoding="utf-8",
        )
        launcher = Path(sys.executable).resolve()

        def kind_adapter(
            kind: str,
            payload: bytes,
            *,
            provider: str | None = None,
            model: str | None = None,
            endpoint_id: str | None = None,
            artifact_media_type: str = "image",
        ) -> broll_component_executor.KindAdapter:
            def invoke(
                context: broll_component_executor.AdapterContext,
            ) -> broll_component_executor.AdapterResult:
                self.adapter_calls[kind].append(context)
                context.staging_path.write_bytes(payload)
                return broll_component_executor.AdapterResult(
                    invocation_evidence={
                        "adapter_id": f"{kind}-fixture",
                        "actual_output_job_path": context.staging_job_path,
                    },
                    qa={"passed": True, "checks": ["adapter_completed"]},
                )

            return broll_component_executor.KindAdapter(
                kind=kind,
                approved_executor="test-executor",
                adapter_id=f"{kind}-fixture",
                adapter_version="1.0.0",
                artifact_media_type=artifact_media_type,
                invoke=invoke,
                provider=provider,
                model=model,
                endpoint_id=endpoint_id,
            )

        return {
            "code_generated": {
                "html-video": broll_component_executor.ReferenceProcessAdapter(
                    adapter_id="html-video-reference-fixture",
                    dependency_id="html-video",
                    approved_executor="test-executor",
                    dependency_root=dependency_root,
                    entrypoint=entrypoint.name,
                    entrypoint_sha256=_sha256(entrypoint),
                    producer_version="approved-version",
                    primary_renderer="HyperFrames",
                    renderer_version="approved-renderer",
                    artifact_media_type="video",
                    brief_loader=lambda *_args: self.code_brief,
                    launcher=launcher,
                    launcher_sha256=_sha256(launcher),
                    argv_template=("{launcher}", "{entrypoint}", "--brief", "{brief_path}", "--output", "{output_path}"),
                    self_contained_wrapper=True,
                )
            },
            "external_stock": kind_adapter(
                "external_stock",
                self.stock_output,
                artifact_media_type="video",
            ),
            "ai_generated": kind_adapter(
                "ai_generated",
                self.ai_output,
                provider="xAI",
                model="grok-imagine-video",
                endpoint_id="video-generation",
            ),
            "artifact_probe": broll_component_executor.ArtifactProbe(
                probe_id="fixture-media-probe",
                probe_version="1.0.0",
                probe=media_probe,
            ),
        }

    def _execute_component(
        self,
        job: state.JobState,
        request: broll_component_executor.ComponentExecutionRequest,
        *,
        adapters: object,
    ) -> broll_component_executor.ComponentArtifact:
        self.assertEqual(job.job_id, self.job.job_id)
        self.assertEqual(job.job_dir, self.job.job_dir)
        self.assertIs(adapters, self.component_adapters)
        self.execution_requests.append(request)
        recipe_value = request.recipe
        component = next(
            item for item in recipe_value["components"]
            if item["component_id"] == request.component_id
        )
        output = (
            self.job.job_dir / "component-output" / str(recipe_value["segment_id"])
            / f"{request.component_id}.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"{recipe_value['segment_id']}:{request.component_id}".encode())
        relative = output.relative_to(self.job.job_dir).as_posix()
        digest = _sha256(output)
        contract = component["artifact_contract"]
        evidence = {"output_job_path": relative, "output_sha256": digest}
        if component["kind"] == "code_generated":
            evidence["primary_renderer"] = component["primary_renderer"]
        canonical = json.dumps(
            {"recipe": recipe_value, "component_id": request.component_id},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return broll_component_executor.ComponentArtifact(
            schema_version=1,
            status="success",
            job_id=self.job.job_id,
            segment_id=str(recipe_value["segment_id"]),
            component_id=request.component_id,
            kind=str(component["kind"]),
            strategy_revision=int(recipe_value["strategy_revision"]),
            media_type="image",
            render_window=component["render_window"],
            z_index=int(component["render_window"]["z_index"]),
            layout_slot=str(component["render_window"]["layout_slot"]),
            opacity=float(component["render_window"]["opacity"]),
            safe_zone=component["render_window"]["safe_zone"],
            artifact_contract=contract,
            source_media_type=str(component["media_type"]),
            artifact_media_type="image",
            media_probe={
                "media_type": "image",
                "container": "png",
                "codec": "png",
                "pixel_format": "rgba" if contract["alpha"] else "rgb24",
                "alpha": contract["alpha"],
                "width": 1080,
                "height": 1920,
                "fps": None,
                "frame_count": 1,
                "duration": None,
            },
            input_sha256=hashlib.sha256(canonical).hexdigest(),
            job_path=relative,
            byte_count=output.stat().st_size,
            output_sha256=digest,
            invocation_evidence=evidence,
            qa={"passed": True, "checks": ["fixture"]},
            error_code=None,
        )

    def _ffmpeg(self, command: tuple[str, ...], _timeout: float) -> None:
        self.ffmpeg_calls.append(command)
        Path(command[-1]).write_bytes(b"composed-segment")

    @staticmethod
    def _probe(_path: Path) -> dict[str, object]:
        return {
            "width": 1080,
            "height": 1920,
            "r_frame_rate": "24/1",
            "nb_read_frames": "72",
            "duration": 3.0,
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
        }

    @staticmethod
    def _frame(_video: Path, timestamp: float, output: Path) -> None:
        output.write_bytes(f"frame:{timestamp:.6f}".encode())

    @staticmethod
    def _assemble(paths: list[Path], output: Path) -> None:
        output.write_bytes(b"".join(path.read_bytes() for path in paths))

    def _prepare_canary(self) -> dict[str, object]:
        return visual_canary.prepare_visual_canary(
            self.job,
            segment_ids=("seg-011",),
            component_adapters=self.component_adapters,
            ffmpeg_runner=self._ffmpeg,
            probe=self._probe,
            frame_extractor=self._frame,
            assembler=self._assemble,
        )

    def _prepare_assets(self) -> Path:
        return visual_assets.prepare_visual_assets(
            self.job,
            component_adapters=self.component_adapters,
            segment_ffmpeg_runner=self._ffmpeg,
            segment_probe=self._probe,
            segment_frame_extractor=self._frame,
            segment_assembler=self._assemble,
        )

    @staticmethod
    def _tree_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def _publish_initial_assets(self) -> Path:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            target = self._prepare_assets().parent
        state.approve(self.job, "visual_assets")
        state.revise(
            self.job,
            "visual_assets",
            "retry the same approved stock recipe",
            artifact_scope=("seg-012",),
        )
        return target

    def _approve_revised_plan(
        self,
        mutate: object,
    ) -> dict[str, object]:
        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        review_path = self.job.job_dir / "07-visual-direction/visual-routing.md"
        changed = contract_artifacts.read_json_artifact(plan_path)
        mutate(changed)
        unsigned = {
            key: value for key, value in changed.items()
            if key != "visual_plan_sha256"
        }
        changed["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        changed = visual_plan.validate_visual_plan(changed)
        state.revise(self.job, "visual_direction", "review revised visual generation")
        contract_artifacts.write_json_artifact(plan_path, changed)
        contract_artifacts.write_text_artifact(review_path, "# Revised generation\n")
        state.mark_ready(self.job, "visual_direction", (plan_path, review_path))
        state.approve(self.job, "visual_direction")
        self.plan = changed
        return changed

    @staticmethod
    def _increment_code_revision(plan: dict[str, object]) -> None:
        plan["segments"][0]["shot_recipe"]["strategy_revision"] += 1

    def _replace_stock_candidate(
        self,
        plan: dict[str, object],
        *,
        revision_delta: int,
    ) -> None:
        payload = b"revised-approved-stock-source"
        segment = plan["segments"][1]
        component = segment["shot_recipe"]["components"][0]
        digest = hashlib.sha256(payload).hexdigest()
        revised = {
            **segment["bindings"]["component-1"],
            "provider_asset_id": "202",
            "asset_page": "https://www.pexels.com/video/202",
            "job_path": f"stock/aa/{'a' * 64}.mp4",
            "license_snapshot": f"stock/aa/{'a' * 64}.license.json",
            "sha256": digest,
        }
        segment["bindings"]["component-1"] = revised
        component.update(revised)
        segment["candidate_snapshots"]["component-1"][0]["asset_id"] = "202"
        segment["shot_recipe"]["strategy_revision"] += revision_delta
        stock_path = self.job.job_dir / revised["job_path"]
        stock_path.parent.mkdir(parents=True, exist_ok=True)
        stock_path.write_bytes(payload)
        executor_fixtures._write_stock_license(self.job, component, payload)

    def test_canary_executes_only_exact_approved_component_bindings(self) -> None:
        prohibited = {
            "router_compile": mock.Mock(
                side_effect=AssertionError("router compile must not run")
            ),
            "stock_search": mock.Mock(
                side_effect=AssertionError("stock search must not run")
            ),
            "official_material_fetch": mock.Mock(
                side_effect=AssertionError("official material fetch must not run")
            ),
            "local_material_refresh": mock.Mock(
                side_effect=AssertionError("local material refresh must not run")
            ),
        }
        with mock.patch.object(
            visual_plan,
            "_canonical_compile_strategy",
            prohibited["router_compile"],
        ), mock.patch.object(
            stock_media,
            "freeze_search_snapshot",
            prohibited["stock_search"],
        ), mock.patch.object(
            prepare_official_sources,
            "source_download_command",
            prohibited["official_material_fetch"],
        ), mock.patch.object(
            cover_direction,
            "_user_material",
            prohibited["local_material_refresh"],
        ):
            manifest = self._prepare_canary()

        self.assertEqual(manifest["segment_ids"], ["seg-011"])
        self.assertEqual(len(self.adapter_calls["code_generated"]), 1)
        context = self.adapter_calls["code_generated"][0]
        component = context.component
        approved = self.plan["segments"][0]["shot_recipe"]["components"][0]
        self.assertEqual(component["kind"], "code_generated")
        for field in (
            "dependency_id",
            "entrypoint",
            "producer_version",
            "brief_sha256",
            "primary_renderer",
            "renderer_version",
        ):
            self.assertEqual(component[field], approved[field])
        self.assertEqual(context.component_id, component["component_id"])
        self.assertEqual(len(self.ffmpeg_calls), 1)
        receipt = material_usage.load_current_receipt(
            self.job, "visual_canary"
        )
        self.assertEqual(receipt["references"], [])
        self.assertIn(
            "08-visual-canary/material-usage.json",
            {
                record["path"]
                for record in self.job.stages["visual_canary"]["artifacts"]
            },
        )
        for entrypoint in prohibited.values():
            entrypoint.assert_not_called()

    def test_formal_assets_copy_canary_bytes_and_execute_only_remaining_recipe(self) -> None:
        prohibited = {
            "router_compile": mock.Mock(side_effect=AssertionError("compile called")),
            "stock_search": mock.Mock(side_effect=AssertionError("search called")),
            "official_material_fetch": mock.Mock(
                side_effect=AssertionError("official fetch called")
            ),
            "local_material_refresh": mock.Mock(
                side_effect=AssertionError("local refresh called")
            ),
        }
        with mock.patch.object(
            visual_plan,
            "_canonical_compile_strategy",
            prohibited["router_compile"],
        ), mock.patch.object(
            stock_media,
            "freeze_search_snapshot",
            prohibited["stock_search"],
        ), mock.patch.object(
            prepare_official_sources,
            "source_download_command",
            prohibited["official_material_fetch"],
        ), mock.patch.object(
            cover_direction,
            "_user_material",
            prohibited["local_material_refresh"],
        ):
            canary = self._prepare_canary()
            state.approve(self.job, "visual_canary")
            calls_after_canary = len(self.ffmpeg_calls)
            track = self._prepare_assets()

        self.assertTrue(track.is_file())
        self.assertEqual(len(self.ffmpeg_calls) - calls_after_canary, 3)
        self.assertEqual(
            {kind: len(calls) for kind, calls in self.adapter_calls.items()},
            {"code_generated": 1, "external_stock": 1, "ai_generated": 1},
        )
        ai_component = self.adapter_calls["ai_generated"][0].component
        approved_ai = self.plan["segments"][2]["shot_recipe"]["components"][0]
        self.assertEqual(
            (
                ai_component["kind"],
                ai_component["provider"],
                ai_component["model"],
                ai_component["endpoint_id"],
            ),
            (
                approved_ai["kind"],
                approved_ai["provider"],
                approved_ai["model"],
                approved_ai["endpoint_id"],
            ),
        )
        stock_component = self.adapter_calls["external_stock"][0].component
        approved_stock = self.plan["segments"][1]["shot_recipe"]["components"][0]
        for field in (
            "provider",
            "provider_asset_id",
            "asset_page",
            "job_path",
            "license_snapshot",
            "sha256",
        ):
            self.assertEqual(stock_component[field], approved_stock[field])
        for entrypoint in prohibited.values():
            entrypoint.assert_not_called()
        manifest = contract_artifacts.read_json_artifact(
            self.job.job_dir / "09-visual-assets/asset-manifest.json"
        )
        receipt = material_usage.load_current_receipt(
            self.job, "visual_assets"
        )
        self.assertEqual(receipt["references"], [])
        self.assertIn(
            "09-visual-assets/material-usage.json",
            {
                record["path"]
                for record in self.job.stages["visual_assets"]["artifacts"]
            },
        )
        self.assertEqual(manifest["reused_canary_segment_ids"], ["seg-011"])
        canary_segment = canary["segments"][0]
        formal_segment = next(
            item for item in manifest["segments"] if item["segment_id"] == "seg-011"
        )
        self.assertEqual(formal_segment["video_sha256"], canary_segment["video_sha256"])
        self.assertEqual(formal_segment["video_bytes"], canary_segment["video_bytes"])
        self.assertEqual(
            Path(formal_segment["video_path"]).read_bytes(),
            Path(canary_segment["video_path"]).read_bytes(),
        )
        arroll_segment = next(
            item for item in manifest["segments"] if item["segment_id"] == "seg-014"
        )
        self.assertEqual(arroll_segment["composition_family"], "no_broll")
        self.assertEqual(arroll_segment["component_artifacts"], [])
        self.assertEqual(arroll_segment["arroll_sha256"], _sha256(self.arroll))
        self.assertEqual(arroll_segment["arroll_bytes"], self.arroll.stat().st_size)

    def test_scoped_component_failure_preserves_the_published_generation(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self._prepare_assets()
        state.approve(self.job, "visual_assets")
        state.revise(
            self.job,
            "visual_assets",
            "rebuild the approved stock segment",
            artifact_scope=("seg-012",),
        )
        target = self.job.job_dir / "09-visual-assets"
        before = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*") if path.is_file()
        }

        def stop_on_ai(job: object, request: object, *, adapters: object) -> object:
            if request.recipe["segment_id"] == "seg-012":
                raise RuntimeError("component execution stopped")
            return self._execute_component(job, request, adapters=adapters)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=stop_on_ai,
        ), self.assertRaisesRegex(RuntimeError, "component execution stopped"):
            self._prepare_assets()

        after = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertEqual(list(self.job.job_dir.glob(".09-visual-assets.stage-*")), [])

    def test_scoped_composition_failure_preserves_the_published_generation(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self._prepare_assets()
        state.approve(self.job, "visual_assets")
        state.revise(
            self.job,
            "visual_assets",
            "rebuild the approved stock segment",
            artifact_scope=("seg-012",),
        )
        target = self.job.job_dir / "09-visual-assets"
        before = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*") if path.is_file()
        }

        def stop_composition(_command: tuple[str, ...], _timeout: float) -> None:
            raise RuntimeError("composition stopped")

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), self.assertRaisesRegex(RuntimeError, "composition stopped"):
            visual_assets.prepare_visual_assets(
                self.job,
                component_adapters=self.component_adapters,
                segment_ffmpeg_runner=stop_composition,
                segment_probe=self._probe,
                segment_frame_extractor=self._frame,
                segment_assembler=self._assemble,
            )

        after = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertEqual(list(self.job.job_dir.glob(".09-visual-assets.stage-*")), [])

    def test_canary_reuse_checks_current_component_artifact_bytes(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
        state.approve(self.job, "visual_canary")
        component = self.job.job_dir / "component-output/seg-011/component-1.png"
        component.write_bytes(b"changed-component")
        execute = mock.Mock(side_effect=AssertionError("must not execute"))
        calls = len(self.ffmpeg_calls)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            execute,
        ), self.assertRaises(RuntimeError):
            self._prepare_assets()

        execute.assert_not_called()
        self.assertEqual(len(self.ffmpeg_calls), calls)

    def test_scoped_retry_keeps_the_approved_strategy_and_binding(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self._prepare_assets()
            state.approve(self.job, "visual_assets")
            state.revise(
                self.job,
                "visual_assets",
                "retry the same approved strategy",
                artifact_scope=("seg-012",),
            )
            self.execution_requests.clear()
            calls_before_retry = len(self.ffmpeg_calls)
            self._prepare_assets()

        self.assertEqual(len(self.execution_requests), 1)
        self.assertEqual(len(self.ffmpeg_calls) - calls_before_retry, 1)
        component = self.execution_requests[0].recipe["components"][0]
        approved = self.plan["segments"][1]["shot_recipe"]["components"][0]
        fields = (
            "kind",
            "semantic_role",
            "provider",
            "provider_asset_id",
            "asset_page",
        )
        self.assertEqual(
            {key: component[key] for key in fields},
            {key: approved[key] for key in fields},
        )
        self.assertEqual(
            self.execution_requests[0].recipe["strategy_revision"],
            self.plan["segments"][1]["shot_recipe"]["strategy_revision"],
        )

    def test_same_strategy_retry_keeps_code_ai_and_stock_bindings(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        self._prepare_assets()
        state.approve(self.job, "visual_assets")
        cases = (
            (
                "seg-011",
                "code_generated",
                (
                    "kind",
                    "semantic_role",
                    "dependency_id",
                    "entrypoint",
                    "primary_renderer",
                    "renderer_version",
                ),
            ),
            (
                "seg-012",
                "external_stock",
                (
                    "kind",
                    "semantic_role",
                    "provider",
                    "provider_asset_id",
                    "asset_page",
                    "sha256",
                ),
            ),
            (
                "seg-013",
                "ai_generated",
                (
                    "kind",
                    "semantic_role",
                    "provider",
                    "model",
                    "endpoint_id",
                ),
            ),
        )
        for identifier, kind, fields in cases:
            before_calls = {
                name: len(values) for name, values in self.adapter_calls.items()
            }
            state.revise(
                self.job,
                "visual_assets",
                f"retry the approved {kind} recipe",
                artifact_scope=(identifier,),
            )
            self._prepare_assets()
            payload = contract_artifacts.read_json_artifact(
                self.job.job_dir / "09-visual-assets/asset-manifest.json"
            )
            rendered = next(
                item for item in payload["segments"]
                if item["segment_id"] == identifier
            )
            segment = next(
                item for item in self.plan["segments"]
                if item["segment_id"] == identifier
            )
            approved = segment["shot_recipe"]["components"][0]
            replayed = rendered["component_artifacts"][0]
            self.assertEqual(replayed["kind"], kind)
            self.assertEqual(
                replayed["strategy_revision"],
                segment["shot_recipe"]["strategy_revision"],
            )
            context = self.adapter_calls[kind][0]
            for field in fields:
                self.assertEqual(context.component[field], approved[field])
            self.assertEqual(
                {name: len(values) for name, values in self.adapter_calls.items()},
                before_calls,
            )
            state.approve(self.job, "visual_assets")

    def test_changed_stock_candidate_creates_a_reviewable_plan_generation(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        self._prepare_assets()
        state.approve(self.job, "visual_assets")
        formal = self.job.job_dir / "09-visual-assets"
        before = self._tree_bytes(formal)
        previous_job_revision = self.job.revision
        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        review_path = self.job.job_dir / "07-visual-direction/visual-routing.md"
        changed = contract_artifacts.read_json_artifact(plan_path)
        segment = changed["segments"][1]
        component = segment["shot_recipe"]["components"][0]
        revised_binding = {
            **segment["bindings"]["component-1"],
            "provider_asset_id": "202",
            "asset_page": "https://www.pexels.com/video/202",
            "job_path": "stock/bb/" + "b" * 64 + ".mp4",
            "license_snapshot": "stock/bb/" + "b" * 64 + ".license.json",
            "sha256": "b" * 64,
        }
        segment["bindings"]["component-1"] = revised_binding
        component.update(revised_binding)
        segment["candidate_snapshots"]["component-1"][0]["asset_id"] = "202"
        previous_strategy_revision = component_revision = segment["shot_recipe"][
            "strategy_revision"
        ]
        segment["shot_recipe"]["strategy_revision"] = component_revision + 1
        unsigned = {
            key: value for key, value in changed.items() if key != "visual_plan_sha256"
        }
        changed["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        changed = visual_plan.validate_visual_plan(changed)

        state.revise(
            self.job,
            "visual_direction",
            "review the revised stock candidate",
        )
        contract_artifacts.write_json_artifact(plan_path, changed)
        contract_artifacts.write_text_artifact(
            review_path,
            "# Revised stock candidate\n",
        )
        state.mark_ready(
            self.job,
            "visual_direction",
            (plan_path, review_path),
        )

        self.assertEqual(
            self.job.stages["visual_direction"]["status"],
            "ready_for_review",
        )
        self.assertNotEqual(
            changed["visual_plan_sha256"],
            self.plan["visual_plan_sha256"],
        )
        self.assertEqual(
            changed["segments"][1]["shot_recipe"]["strategy_revision"],
            previous_strategy_revision + 1,
        )
        self.assertGreater(self.job.revision, previous_job_revision)
        self.assertEqual(self._tree_bytes(formal), before)

    def test_formal_replay_requires_the_complete_published_artifact_records(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self._prepare_assets()
        workflow_path = self.job.job_dir / "workflow.json"
        workflow = contract_artifacts.read_json_artifact(workflow_path)
        workflow["stages"]["visual_assets"]["artifacts"].pop(0)
        contract_artifacts.write_json_artifact(workflow_path, workflow)

        with self.assertRaises(visual_assets_v2.VisualAssetsV2Error):
            self._prepare_assets()

    def test_formal_publish_records_journal_before_stage_install_failure(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)
        actual_replace = visual_assets_v2.os.replace
        observed: list[str] = []

        def fail_stage_install(source: object, destination: object) -> None:
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.name.startswith(".09-visual-assets.stage-")
                and destination_path == target
            ):
                journal = self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
                observed.append(
                    contract_artifacts.read_json_artifact(journal)["state"]
                )
                raise OSError("stage install stopped")
            actual_replace(source, destination)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), mock.patch.object(
            visual_assets_v2.os,
            "replace",
            side_effect=fail_stage_install,
        ), self.assertRaises(OSError):
            self._prepare_assets()

        self.assertEqual(observed, ["backed_up"])
        self.assertEqual(self._tree_bytes(target), before)
        self.assertFalse(
            (self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME).exists()
        )
        self.assertEqual(list(self.job.job_dir.glob(".09-visual-assets.backup-*")), [])

    def test_mark_ready_failure_restores_the_previous_formal_generation(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)
        stage_before = json.loads(json.dumps(self.job.stages["visual_assets"]))
        revision_before = self.job.revision

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), mock.patch.object(
            visual_assets_v2.state,
            "mark_ready",
            side_effect=RuntimeError("state publication stopped"),
        ), self.assertRaisesRegex(RuntimeError, "state publication stopped"):
            self._prepare_assets()

        self.assertEqual(self._tree_bytes(target), before)
        self.assertEqual(self.job.stages["visual_assets"], stage_before)
        self.assertEqual(self.job.revision, revision_before)
        self.assertFalse(
            (self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME).exists()
        )

    def test_interrupted_formal_publish_is_recovered_before_component_execution(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), mock.patch.object(
            visual_assets_v2.state,
            "mark_ready",
            side_effect=KeyboardInterrupt(),
        ), self.assertRaises(KeyboardInterrupt):
            self._prepare_assets()

        journal = self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
        self.assertTrue(journal.is_file())
        self.assertEqual(
            contract_artifacts.read_json_artifact(journal)["state"],
            "installed",
        )
        self.assertEqual(len(list(self.job.job_dir.glob(".09-visual-assets.backup-*"))), 1)

        def stop_after_recovery(
            _job: object,
            _request: object,
            *,
            adapters: object,
        ) -> object:
            self.assertIs(adapters, self.component_adapters)
            self.assertEqual(self._tree_bytes(target), before)
            raise RuntimeError("recovery observed")

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=stop_after_recovery,
        ), self.assertRaisesRegex(RuntimeError, "recovery observed"):
            self._prepare_assets()

        self.assertEqual(self._tree_bytes(target), before)
        self.assertFalse(journal.exists())
        self.assertEqual(list(self.job.job_dir.glob(".09-visual-assets.backup-*")), [])

    def test_default_canary_selection_covers_families_within_thirty_seconds(self) -> None:
        segments = json.loads(json.dumps(self.plan["segments"]))
        segments[1]["shot_recipe"]["composition"]["family"] = "comparison_split"
        segments[2]["shot_recipe"]["composition"]["family"] = "evidence_stack"
        selected = visual_canary.select_representative_segments(
            segments
        )
        self.assertEqual(
            [item["segment_id"] for item in selected],
            ["seg-011", "seg-012", "seg-013"],
        )
        families = [
            item["shot_recipe"]["composition"]["family"] for item in selected
        ]
        self.assertEqual(len(families), len(set(families)))
        self.assertLessEqual(
            sum(float(item["end"]) - float(item["start"]) for item in selected),
            visual_canary.MAX_CANARY_SECONDS,
        )
        self.assertNotIn("seg-014", [item["segment_id"] for item in selected])
        with self.assertRaises(visual_canary.VisualCanaryError):
            visual_canary.select_representative_segments(
                segments,
                requested=("seg-011", "seg-011"),
            )

    def test_hybrid_components_execute_in_approved_reading_order(self) -> None:
        segment = _segment(
            "seg-020",
            12.0,
            ("code_generated", "ai_generated"),
        )
        recipe_value = segment["shot_recipe"]
        recipe_value["composition"]["reading_order"] = [
            "component-2",
            "component-1",
        ]
        observed: list[str] = []

        def execute(
            job: object,
            request: broll_component_executor.ComponentExecutionRequest,
            *,
            adapters: object,
        ) -> broll_component_executor.ComponentArtifact:
            observed.append(request.component_id)
            return self._execute_component(job, request, adapters=adapters)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=execute,
        ):
            artifacts = visual_canary.execute_approved_components(
                self.job,
                segment,
                adapters=self.component_adapters,
            )

        self.assertEqual(observed, ["component-2", "component-1"])
        self.assertEqual(
            [artifact.component_id for artifact in artifacts],
            observed,
        )

    def test_second_canary_prepare_replays_without_any_generation_call(self) -> None:
        first = self._prepare_canary()
        execute = mock.Mock(side_effect=AssertionError("component must not execute"))
        ffmpeg = mock.Mock(side_effect=AssertionError("ffmpeg must not run"))
        assembler = mock.Mock(side_effect=AssertionError("assembler must not run"))

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            execute,
        ):
            second = visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-011",),
                component_adapters=self.component_adapters,
                ffmpeg_runner=ffmpeg,
                probe=self._probe,
                frame_extractor=self._frame,
                assembler=assembler,
            )

        self.assertEqual(second, first)
        execute.assert_not_called()
        ffmpeg.assert_not_called()
        assembler.assert_not_called()

    def test_same_segment_id_in_new_approved_plan_replaces_canary_generation(self) -> None:
        first = self._prepare_canary()
        state.approve(self.job, "visual_canary")
        self._approve_revised_plan(self._increment_code_revision)

        second = self._prepare_canary()

        self.assertEqual(second["segment_ids"], ["seg-011"])
        self.assertNotEqual(second["visual_plan_sha256"], first["visual_plan_sha256"])
        self.assertNotEqual(second["canary_sha256"], first["canary_sha256"])
        self.assertEqual(
            list(self.job.job_dir.glob(".08-visual-canary.stage-*")),
            [],
        )

    def test_multi_segment_assembler_failure_keeps_previous_canary(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        target = self.job.job_dir / "08-visual-canary"
        before = self._tree_bytes(target)
        self._approve_revised_plan(self._increment_code_revision)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), self.assertRaisesRegex(RuntimeError, "canary assembly stopped"):
            visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-011", "seg-012"),
                component_adapters=self.component_adapters,
                ffmpeg_runner=self._ffmpeg,
                probe=self._probe,
                frame_extractor=self._frame,
                assembler=mock.Mock(
                    side_effect=RuntimeError("canary assembly stopped")
                ),
            )

        self.assertEqual(self._tree_bytes(target), before)
        self.assertEqual(list(self.job.job_dir.glob(".08-visual-canary.stage-*")), [])

    def test_canary_mark_ready_failure_restores_previous_generation(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        target = self.job.job_dir / "08-visual-canary"
        before = self._tree_bytes(target)
        self._approve_revised_plan(self._increment_code_revision)
        stage_before = json.loads(json.dumps(self.job.stages["visual_canary"]))
        revision_before = self.job.revision

        with mock.patch.object(
            visual_canary.state,
            "mark_ready",
            side_effect=RuntimeError("canary state publication stopped"),
        ), self.assertRaisesRegex(RuntimeError, "canary state publication stopped"):
            self._prepare_canary()

        self.assertEqual(self._tree_bytes(target), before)
        self.assertEqual(self.job.stages["visual_canary"], stage_before)
        self.assertEqual(self.job.revision, revision_before)

    def test_canary_interruption_recovers_previous_generation_before_retry(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        target = self.job.job_dir / "08-visual-canary"
        before = self._tree_bytes(target)
        self._approve_revised_plan(self._increment_code_revision)

        with mock.patch.object(
            visual_canary.state,
            "mark_ready",
            side_effect=KeyboardInterrupt(),
        ), self.assertRaises(KeyboardInterrupt):
            self._prepare_canary()

        journal = self.job.job_dir / visual_canary.PUBLICATION_JOURNAL_NAME
        self.assertTrue(journal.is_file())

        def stop_after_recovery(
            _job: object,
            _request: object,
            *,
            adapters: object,
        ) -> object:
            self.assertIs(adapters, self.component_adapters)
            self.assertEqual(self._tree_bytes(target), before)
            raise RuntimeError("canary recovery observed")

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=stop_after_recovery,
        ), self.assertRaisesRegex(RuntimeError, "canary recovery observed"):
            self._prepare_canary()

        self.assertEqual(self._tree_bytes(target), before)
        self.assertFalse(journal.exists())

    def test_plan_revision_reuses_unchanged_formal_segments(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target / "segments")
        self._approve_revised_plan(self._increment_code_revision)
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
        self.execution_requests.clear()
        self.ffmpeg_calls.clear()

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_assets()

        self.assertEqual(self.execution_requests, [])
        self.assertEqual(self.ffmpeg_calls, [])
        after = self._tree_bytes(target / "segments")
        for name, payload in before.items():
            if not name.startswith("seg-011/"):
                self.assertEqual(after[name], payload, name)
        manifest = contract_artifacts.read_json_artifact(target / "asset-manifest.json")
        self.assertEqual(manifest["visual_plan_sha256"], self.plan["visual_plan_sha256"])
        self.assertEqual(manifest["reused_formal_segment_ids"], ["seg-012", "seg-013", "seg-014"])
        self.assertEqual(manifest["reused_canary_segment_ids"], ["seg-011"])
        revision = self.job.revision
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=AssertionError("ready replay must not generate"),
        ):
            self._prepare_assets()
        self.assertEqual(self.job.revision, revision)
        self.assertEqual(self._tree_bytes(target / "segments"), after)

    def test_revised_plan_cannot_hide_corrupt_formal_generation(self) -> None:
        target = self._publish_initial_assets()
        self._approve_revised_plan(self._increment_code_revision)
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
        (target / "segments/seg-012/segment.mp4").write_bytes(b"corrupt")
        before = self._tree_bytes(target)
        revision = self.job.revision
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), self.assertRaises(visual_assets_v2.VisualAssetsV2Error):
            self._prepare_assets()
        self.assertEqual(self.job.revision, revision)
        self.assertEqual(self._tree_bytes(target), before)

    def test_plan_revision_renders_only_changed_noncanary_segment(self) -> None:
        target = self._publish_initial_assets()
        self._approve_revised_plan(
            lambda plan: self._replace_stock_candidate(plan, revision_delta=1)
        )
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self.execution_requests.clear()
            self.ffmpeg_calls.clear()
            self._prepare_assets()
        self.assertEqual(
            [item.recipe["segment_id"] for item in self.execution_requests], ["seg-012"]
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        manifest = contract_artifacts.read_json_artifact(target / "asset-manifest.json")
        self.assertEqual(manifest["reused_formal_segment_ids"], ["seg-013", "seg-014"])
        self.assertEqual(manifest["reused_canary_segment_ids"], ["seg-011"])

    def test_revised_plan_prefers_newly_approved_canary_bytes(self) -> None:
        target = self._publish_initial_assets()
        self._approve_revised_plan(
            lambda plan: self._replace_stock_candidate(plan, revision_delta=1)
        )
        def new_canary(command: tuple[str, ...], _timeout: float) -> None:
            Path(command[-1]).write_bytes(b"newly-approved-canary")

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            with mock.patch.object(self, "_ffmpeg", side_effect=new_canary):
                self._prepare_canary()
            state.approve(self.job, "visual_canary")
            self._prepare_assets()
        self.assertEqual(
            (target / "segments/seg-011/segment.mp4").read_bytes(),
            b"newly-approved-canary",
        )

    def test_segment_reuse_fingerprint_covers_render_dependencies(self) -> None:
        original = self.plan["segments"][1]
        baseline = visual_assets_v2._segment_input_identity(self.plan, original)
        mutations = {
            "visible_text": lambda item: item["visible_text"].append({"text": "新文案"}),
            "timing": lambda item: item.update(start=item["start"] + 1 / 24),
            "binding": lambda item: item["bindings"]["component-1"].update(sha256="e" * 64),
            "revision": lambda item: item["shot_recipe"].update(strategy_revision=2),
            "avatar": lambda item: item["shot_recipe"]["composition"]["avatar"]["position"].update(x=760),
            "opacity": lambda item: item["shot_recipe"]["components"][0]["render_window"].update(opacity=0.5),
        }
        for name, mutate in mutations.items():
            with self.subTest(dependency=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                self.assertNotEqual(
                    baseline, visual_assets_v2._segment_input_identity(self.plan, changed)
                )
        for key in ("content_analysis_sha256", "edit_plan_sha256", "timeline_map_sha256", "edited_aroll_sha256", "canvas"):
            with self.subTest(context=key):
                changed_plan = copy.deepcopy(self.plan)
                changed_plan[key] = {"width": 720, "height": 1280, "fps": 24} if key == "canvas" else "e" * 64
                self.assertNotEqual(
                    baseline, visual_assets_v2._segment_input_identity(changed_plan, original)
                )

    def test_revision_reuse_rejects_missing_lineage(self) -> None:
        target = self._publish_initial_assets()
        changed = copy.deepcopy(self.plan)
        changed["visual_plan_sha256"] = "f" * 64
        self.job.stages["visual_assets"]["lineage"] = []
        with self.assertRaisesRegex(visual_assets_v2.VisualAssetsV2Error, "approval evidence"):
            visual_assets_v2._load_segments(
                self.job, changed, target, require_manifest=False, probe=self._probe
            )

    def test_revision_reuse_omits_deleted_segment(self) -> None:
        target = self._publish_initial_assets()
        changed = copy.deepcopy(self.plan)
        changed["visual_plan_sha256"] = "f" * 64
        changed["segments"].pop()
        changed["duration"] = 9.0
        loaded = visual_assets_v2._load_segments(
            self.job, changed, target, require_manifest=False, probe=self._probe
        )
        self.assertEqual(set(loaded), {"seg-011", "seg-012", "seg-013"})

    def test_revision_reuse_rejects_changed_component_bytes(self) -> None:
        target = self._publish_initial_assets()
        changed = copy.deepcopy(self.plan)
        changed["visual_plan_sha256"] = "f" * 64
        (self.job.job_dir / "component-output/seg-012/component-1.png").write_bytes(b"corrupt")
        with self.assertRaises(visual_assets_v2.VisualAssetsV2Error):
            visual_assets_v2._load_segments(
                self.job, changed, target, require_manifest=False, probe=self._probe
            )

    def test_revision_reuse_rejects_previous_renderer_contract(self) -> None:
        target = self._publish_initial_assets()
        changed = copy.deepcopy(self.plan)
        changed["visual_plan_sha256"] = "f" * 64
        with mock.patch.object(segment_render, "RENDERER_CONTRACT_VERSION", "next-contract"):
            with self.assertRaisesRegex(visual_assets_v2.VisualAssetsV2Error, "manifest is invalid"):
                visual_assets_v2._load_segments(
                    self.job, changed, target, require_manifest=False, probe=self._probe
                )

    def test_scope_reuses_current_formal_before_older_canary(self) -> None:
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_canary()
            state.approve(self.job, "visual_canary")
            target = self._prepare_assets().parent
        state.approve(self.job, "visual_assets")
        state.revise(
            self.job,
            "visual_assets",
            "rebuild the approved code segment",
            artifact_scope=("seg-011",),
        )

        def render_first_scope(command: tuple[str, ...], _timeout: float) -> None:
            output = Path(command[-1])
            marker = b"rebuilt-seg-011" if "seg-011" in str(output) else b"other"
            output.write_bytes(marker)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            visual_assets.prepare_visual_assets(
                self.job,
                component_adapters=self.component_adapters,
                segment_ffmpeg_runner=render_first_scope,
                segment_probe=self._probe,
                segment_frame_extractor=self._frame,
                segment_assembler=self._assemble,
            )
        first_bytes = (target / "segments/seg-011/segment.mp4").read_bytes()
        self.assertEqual(first_bytes, b"rebuilt-seg-011")
        state.approve(self.job, "visual_assets")
        state.revise(
            self.job,
            "visual_assets",
            "rebuild the approved stock segment",
            artifact_scope=("seg-012",),
        )

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            self._prepare_assets()

        self.assertEqual(
            (target / "segments/seg-011/segment.mp4").read_bytes(),
            first_bytes,
        )

    def test_stock_candidate_change_requires_new_approved_strategy_revision(self) -> None:
        visual_canary.prepare_visual_canary(
            self.job,
            segment_ids=("seg-012",),
            component_adapters=self.component_adapters,
            ffmpeg_runner=self._ffmpeg,
            probe=self._probe,
            frame_extractor=self._frame,
            assembler=self._assemble,
        )
        state.approve(self.job, "visual_canary")
        formal = self.job.job_dir / "09-visual-assets"
        formal.mkdir()
        (formal / "sentinel.bin").write_bytes(b"current-formal")
        before = self._tree_bytes(formal)
        self._approve_revised_plan(
            lambda plan: self._replace_stock_candidate(plan, revision_delta=0)
        )
        execute = mock.Mock(side_effect=AssertionError("provider must not execute"))

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            execute,
        ), self.assertRaises(visual_canary.VisualCanaryError):
            visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-012",),
                component_adapters=self.component_adapters,
                ffmpeg_runner=self._ffmpeg,
                probe=self._probe,
                frame_extractor=self._frame,
                assembler=self._assemble,
            )

        execute.assert_not_called()
        self.assertEqual(self._tree_bytes(formal), before)

    def test_unapproved_stock_revision_executes_nothing_then_approved_executes(self) -> None:
        visual_canary.prepare_visual_canary(
            self.job,
            segment_ids=("seg-012",),
            component_adapters=self.component_adapters,
            ffmpeg_runner=self._ffmpeg,
            probe=self._probe,
            frame_extractor=self._frame,
            assembler=self._assemble,
        )
        state.approve(self.job, "visual_canary")
        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        review_path = self.job.job_dir / "07-visual-direction/visual-routing.md"
        changed = contract_artifacts.read_json_artifact(plan_path)
        self._replace_stock_candidate(changed, revision_delta=1)
        unsigned = {
            key: value for key, value in changed.items()
            if key != "visual_plan_sha256"
        }
        changed["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        changed = visual_plan.validate_visual_plan(changed)
        state.revise(self.job, "visual_direction", "review revised stock generation")
        contract_artifacts.write_json_artifact(plan_path, changed)
        contract_artifacts.write_text_artifact(review_path, "# Revised stock\n")
        state.mark_ready(self.job, "visual_direction", (plan_path, review_path))
        calls = len(self.adapter_calls["external_stock"])

        with self.assertRaises(visual_canary.VisualCanaryError):
            visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-012",),
                component_adapters=self.component_adapters,
                ffmpeg_runner=self._ffmpeg,
                probe=self._probe,
                frame_extractor=self._frame,
                assembler=self._assemble,
            )
        self.assertEqual(len(self.adapter_calls["external_stock"]), calls)

        state.approve(self.job, "visual_direction")
        self.plan = changed
        visual_canary.prepare_visual_canary(
            self.job,
            segment_ids=("seg-012",),
            component_adapters=self.component_adapters,
            ffmpeg_runner=self._ffmpeg,
            probe=self._probe,
            frame_extractor=self._frame,
            assembler=self._assemble,
        )
        self.assertEqual(len(self.adapter_calls["external_stock"]), calls + 1)

    def test_formal_writer_serializes_concurrent_generation(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        entered = threading.Event()
        release = threading.Event()
        assembler_calls: list[int] = []
        errors: list[BaseException] = []

        def assemble(paths: list[Path], output: Path) -> None:
            assembler_calls.append(len(paths))
            entered.set()
            release.wait(5)
            self._assemble(paths, output)

        def run() -> None:
            try:
                visual_assets_v2.prepare_visual_assets_v2(
                    self.job,
                    component_adapters=self.component_adapters,
                    ffmpeg_runner=self._ffmpeg,
                    probe=self._probe,
                    frame_extractor=self._frame,
                    assembler=assemble,
                )
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            first = threading.Thread(target=run)
            second = threading.Thread(target=run)
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            release.set()
            first.join(10)
            second.join(10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(assembler_calls, [4])

    def test_canary_writer_reloads_independent_job_snapshots(self) -> None:
        first_job = state.load_job(self.job.job_dir)
        second_job = state.load_job(self.job.job_dir)
        entered = threading.Event()
        release = threading.Event()
        assembler_calls: list[int] = []
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def assemble(paths: list[Path], output: Path) -> None:
            assembler_calls.append(len(paths))
            entered.set()
            release.wait(5)
            self._assemble(paths, output)

        def run(snapshot: state.JobState) -> None:
            try:
                results.append(
                    visual_canary.prepare_visual_canary(
                        snapshot,
                        segment_ids=("seg-011",),
                        component_adapters=self.component_adapters,
                        ffmpeg_runner=self._ffmpeg,
                        probe=self._probe,
                        frame_extractor=self._frame,
                        assembler=assemble,
                    )
                )
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            first = threading.Thread(target=run, args=(first_job,))
            second = threading.Thread(target=run, args=(second_job,))
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            release.set()
            first.join(10)
            second.join(10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(assembler_calls, [1])
        self.assertEqual(len(self.execution_requests), 1)
        self.assertEqual(first_job.stages["visual_canary"]["status"], "ready_for_review")
        self.assertEqual(second_job.stages["visual_canary"]["status"], "ready_for_review")

    def test_formal_writer_reloads_independent_job_snapshots(self) -> None:
        self._prepare_canary()
        state.approve(self.job, "visual_canary")
        first_job = state.load_job(self.job.job_dir)
        second_job = state.load_job(self.job.job_dir)
        entered = threading.Event()
        release = threading.Event()
        assembler_calls: list[int] = []
        results: list[Path] = []
        errors: list[BaseException] = []

        def assemble(paths: list[Path], output: Path) -> None:
            assembler_calls.append(len(paths))
            entered.set()
            release.wait(5)
            self._assemble(paths, output)

        def run(snapshot: state.JobState) -> None:
            try:
                results.append(
                    visual_assets_v2.prepare_visual_assets_v2(
                        snapshot,
                        component_adapters=self.component_adapters,
                        ffmpeg_runner=self._ffmpeg,
                        probe=self._probe,
                        frame_extractor=self._frame,
                        assembler=assemble,
                    )
                )
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            first = threading.Thread(target=run, args=(first_job,))
            second = threading.Thread(target=run, args=(second_job,))
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            release.set()
            first.join(10)
            second.join(10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(assembler_calls, [4])
        self.assertEqual(first_job.stages["visual_assets"]["status"], "ready_for_review")
        self.assertEqual(second_job.stages["visual_assets"]["status"], "ready_for_review")

    def test_restore_checkpoint_is_reentrant_and_never_removes_restored_target(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)
        actual_write = visual_assets_v2._write_publication_journal

        def interrupt_before_restored(
            job: state.JobState,
            journal: object,
            publication_state: str,
        ) -> dict[str, object]:
            if publication_state == "restored":
                raise KeyboardInterrupt()
            return actual_write(job, journal, publication_state)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), mock.patch.object(
            visual_assets_v2.state,
            "mark_ready",
            side_effect=RuntimeError("state publication stopped"),
        ), mock.patch.object(
            visual_assets_v2,
            "_write_publication_journal",
            side_effect=interrupt_before_restored,
        ), self.assertRaises(KeyboardInterrupt):
            self._prepare_assets()

        journal = self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
        self.assertEqual(
            contract_artifacts.read_json_artifact(journal)["state"],
            "restoring",
        )
        self.assertEqual(self._tree_bytes(target), before)
        execute = mock.Mock(side_effect=RuntimeError("recovery completed"))
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            execute,
        ), self.assertRaisesRegex(RuntimeError, "recovery completed"):
            self._prepare_assets()
        self.assertEqual(self._tree_bytes(target), before)
        self.assertFalse(journal.exists())

    def test_restored_checkpoint_cleanup_never_removes_restored_target(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)
        actual_clear = visual_assets_v2._clear_publication_journal
        interrupted = False

        def interrupt_after_restored(job: state.JobState) -> None:
            nonlocal interrupted
            journal = contract_artifacts.read_json_artifact(
                job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
            )
            if not interrupted and journal["state"] == "restored":
                interrupted = True
                raise KeyboardInterrupt()
            actual_clear(job)

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ), mock.patch.object(
            visual_assets_v2.state,
            "mark_ready",
            side_effect=RuntimeError("state publication stopped"),
        ), mock.patch.object(
            visual_assets_v2,
            "_clear_publication_journal",
            side_effect=interrupt_after_restored,
        ), self.assertRaises(KeyboardInterrupt):
            self._prepare_assets()

        journal_path = self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
        self.assertEqual(
            contract_artifacts.read_json_artifact(journal_path)["state"],
            "restored",
        )
        self.assertEqual(self._tree_bytes(target), before)
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=RuntimeError("restored cleanup completed"),
        ), self.assertRaisesRegex(RuntimeError, "restored cleanup completed"):
            self._prepare_assets()
        self.assertEqual(self._tree_bytes(target), before)
        self.assertFalse(journal_path.exists())

    def test_direct_formal_entry_rejects_unapproved_plan_before_writer(self) -> None:
        state.revise(self.job, "visual_direction", "plan review is pending")
        recover = mock.Mock(side_effect=AssertionError("recovery must not run"))
        writer = mock.Mock(side_effect=AssertionError("writer must not open"))

        with mock.patch.object(
            visual_assets_v2,
            "_recover_publication",
            recover,
        ), mock.patch.object(
            visual_assets_v2,
            "_visual_assets_writer",
            writer,
        ), self.assertRaises(visual_assets_v2.VisualAssetsV2Error):
            visual_assets_v2.prepare_visual_assets_v2(
                self.job,
                component_adapters=self.component_adapters,
            )

        recover.assert_not_called()
        writer.assert_not_called()

    def test_stale_publication_journal_never_rolls_back_current_formal(self) -> None:
        target = self._publish_initial_assets()
        before = self._tree_bytes(target)
        stale_stage = self.job.job_dir / ".09-visual-assets.stage-stale0000000000"
        stale_stage.mkdir()
        (stale_stage / "asset-manifest.json").write_bytes(b"stale")
        stale_backup = self.job.job_dir / ".09-visual-assets.backup-stale000000000"
        stale_backup.mkdir()
        (stale_backup / "old.bin").write_bytes(b"old")
        stale = {
            "schema_version": 1,
            "job_id": self.job.job_id,
            "state": "installed",
            "target_name": "09-visual-assets",
            "stage_name": stale_stage.name,
            "backup_name": stale_backup.name,
            "artifact_records": [
                {
                    "path": "09-visual-assets/asset-manifest.json",
                    "sha256": "0" * 64,
                    "bytes": 1,
                }
            ],
        }
        journal = self.job.job_dir / visual_assets_v2.PUBLICATION_JOURNAL_NAME
        contract_artifacts.write_json_artifact(journal, stale)

        with self.assertRaisesRegex(
            visual_assets_v2.VisualAssetsV2Error,
            "current visual-assets generation",
        ):
            self._prepare_assets()

        self.assertEqual(self._tree_bytes(target), before)
        self.assertTrue(journal.is_file())
        self.assertTrue(stale_backup.is_dir())

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_real_vertical_track_combines_equal_semantic_kinds_without_refetch(self) -> None:
        valid_aroll = self.root / "valid-aroll.mp4"
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
                "color=c=0x181818:s=1080x1920:r=24:d=12",
                "-frames:v",
                "288",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(valid_aroll),
            ],
            check=True,
            capture_output=True,
        )
        state.revise(self.job, "edit_structure", "use the real acceptance A-roll")
        shutil.copy2(valid_aroll, self.arroll)
        edit_root = self.job.job_dir / "06-edit-structure"
        state.mark_ready(
            self.job,
            "edit_structure",
            (
                edit_root / "edit-plan.json",
                edit_root / "timeline-map.json",
                self.arroll,
            ),
        )
        state.approve(self.job, "edit_structure")

        official_bytes = b"approved official reference"
        official_path = self.job.job_dir / "official/approved-reference.pdf"
        official_path.parent.mkdir(parents=True, exist_ok=True)
        official_path.write_bytes(official_bytes)

        plan_path = self.job.job_dir / "07-visual-direction/visual-plan.json"
        review_path = self.job.job_dir / "07-visual-direction/visual-routing.md"
        changed = contract_artifacts.read_json_artifact(plan_path)
        previous_code = changed["segments"][0]
        hybrid = _segment(
            "seg-011",
            0.0,
            ("official_material", "code_generated"),
        )
        official_binding = hybrid["bindings"]["component-1"]
        official_binding.update(
            {
                "snapshot_path": official_path.relative_to(
                    self.job.job_dir
                ).as_posix(),
                "sha256": hashlib.sha256(official_bytes).hexdigest(),
            }
        )
        hybrid["shot_recipe"]["components"][0].update(official_binding)
        code_binding = previous_code["bindings"]["component-1"]
        hybrid["bindings"]["component-2"] = code_binding
        hybrid["shot_recipe"]["components"][1].update(code_binding)
        changed["segments"][0] = hybrid
        changed["source_summary"]["official_material"] = 1
        changed["edited_aroll_sha256"] = _sha256(self.arroll)
        for segment in changed["segments"]:
            for key in ("visual_strategy", "shot_recipe"):
                avatar = segment[key]["composition"].get("avatar")
                if avatar is not None:
                    avatar["profile"]["source_sha256"] = changed["edited_aroll_sha256"]
        unsigned = {
            key: value for key, value in changed.items()
            if key != "visual_plan_sha256"
        }
        changed["visual_plan_sha256"] = contract_artifacts.sha256_json(unsigned)
        self.plan = visual_plan.validate_visual_plan(changed)
        contract_artifacts.write_json_artifact(plan_path, self.plan)
        contract_artifacts.write_text_artifact(review_path, "# Real acceptance\n")
        state.mark_ready(self.job, "visual_direction", (plan_path, review_path))
        state.approve(self.job, "visual_direction")

        artifacts_by_segment: dict[
            str,
            list[broll_component_executor.ComponentArtifact],
        ] = {}
        colors = {
            "official_material": (184, 58, 50),
            "external_stock": (45, 150, 90),
            "ai_generated": (52, 96, 190),
        }

        def real_component(
            job: state.JobState,
            request: broll_component_executor.ComponentExecutionRequest,
            *,
            adapters: object,
        ) -> broll_component_executor.ComponentArtifact:
            artifact = self._execute_component(job, request, adapters=adapters)
            path = self.job.job_dir / artifact.job_path
            if artifact.kind == "code_generated":
                image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
                ImageDraw.Draw(image).rounded_rectangle(
                    (650, 280, 1010, 660),
                    radius=40,
                    fill=(246, 165, 36, 220),
                )
            else:
                image = Image.new("RGB", (1080, 1920), colors[artifact.kind])
            image.save(path, format="PNG")
            digest = _sha256(path)
            evidence = dict(artifact.invocation_evidence)
            evidence["output_sha256"] = digest
            artifact = dataclasses.replace(
                artifact,
                byte_count=path.stat().st_size,
                output_sha256=digest,
                invocation_evidence=evidence,
            )
            artifacts_by_segment.setdefault(artifact.segment_id, []).append(artifact)
            return artifact

        render_input_hashes: list[list[str]] = []

        def real_runner(command: tuple[str, ...], timeout: float) -> None:
            inputs = [
                Path(command[index + 1])
                for index, value in enumerate(command[:-1])
                if value == "-i"
            ]
            render_input_hashes.append([_sha256(path) for path in inputs])
            segment_render._default_ffmpeg_runner(command, timeout)

        acquisition_calls = {
            "stock_search": mock.Mock(
                side_effect=AssertionError("stock search must not run")
            ),
            "official_fetch": mock.Mock(
                side_effect=AssertionError("official fetch must not run")
            ),
            "local_refresh": mock.Mock(
                side_effect=AssertionError("local refresh must not run")
            ),
        }
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=real_component,
        ), mock.patch.object(
            stock_media,
            "freeze_search_snapshot",
            acquisition_calls["stock_search"],
        ), mock.patch.object(
            prepare_official_sources,
            "source_download_command",
            acquisition_calls["official_fetch"],
        ), mock.patch.object(
            cover_direction,
            "_user_material",
            acquisition_calls["local_refresh"],
        ):
            canary = visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-011", "seg-012", "seg-013"),
                component_adapters=self.component_adapters,
                ffmpeg_runner=real_runner,
                probe=segment_render._default_probe,
            )

        self.assertEqual(
            canary["segment_ids"],
            ["seg-011", "seg-012", "seg-013"],
        )
        self.assertEqual(
            {
                segment_id: [artifact.kind for artifact in artifacts]
                for segment_id, artifacts in artifacts_by_segment.items()
            },
            {
                "seg-011": ["official_material", "code_generated"],
                "seg-012": ["external_stock"],
                "seg-013": ["ai_generated"],
            },
        )
        for index, segment_id in enumerate(("seg-011", "seg-012", "seg-013")):
            self.assertEqual(
                render_input_hashes[index][1:],
                [
                    artifact.output_sha256
                    for artifact in artifacts_by_segment[segment_id]
                ],
            )
        state.approve(self.job, "visual_canary")

        execute_again = mock.Mock(
            side_effect=AssertionError("approved canary components must be reused")
        )
        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            execute_again,
        ), mock.patch.object(
            stock_media,
            "freeze_search_snapshot",
            acquisition_calls["stock_search"],
        ), mock.patch.object(
            prepare_official_sources,
            "source_download_command",
            acquisition_calls["official_fetch"],
        ), mock.patch.object(
            cover_direction,
            "_user_material",
            acquisition_calls["local_refresh"],
        ):
            track = visual_assets.prepare_visual_assets(
                self.job,
                component_adapters=self.component_adapters,
                segment_ffmpeg_runner=real_runner,
                segment_probe=segment_render._default_probe,
            )

        execute_again.assert_not_called()
        for operation in acquisition_calls.values():
            operation.assert_not_called()
        expected_kinds = {
            "seg-011": ["official_material", "code_generated"],
            "seg-012": ["external_stock"],
            "seg-013": ["ai_generated"],
            "seg-014": [],
        }
        hold_hashes: list[str] = []
        for segment_id, kinds in expected_kinds.items():
            manifest = contract_artifacts.read_json_artifact(
                track.parent / "segments" / segment_id / "segment-manifest.json"
            )
            self.assertEqual(
                [artifact["kind"] for artifact in manifest["component_artifacts"]],
                kinds,
            )
            hold_hashes.append(manifest["keyframes"]["hold"]["sha256"])
        self.assertEqual(len(set(hold_hashes)), len(hold_hashes))
        probe = segment_render._default_probe(track)
        self.assertTrue(segment_render._probe_matches(probe, 288))

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required"
    )
    def test_formal_default_assembler_produces_exact_decodable_track(self) -> None:
        template = self.root / "valid-segment.mp4"
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
                "color=c=0x204060:s=1080x1920:r=24:d=3",
                "-frames:v",
                "72",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(template),
            ],
            check=True,
            capture_output=True,
        )

        def valid_segment(_command: tuple[str, ...], _timeout: float) -> None:
            shutil.copy2(template, Path(_command[-1]))

        with mock.patch.object(
            visual_canary.broll_component_executor,
            "execute_component",
            side_effect=self._execute_component,
        ):
            visual_canary.prepare_visual_canary(
                self.job,
                segment_ids=("seg-011",),
                component_adapters=self.component_adapters,
                ffmpeg_runner=valid_segment,
                probe=self._probe,
                frame_extractor=self._frame,
                assembler=self._assemble,
            )
            state.approve(self.job, "visual_canary")
            track = visual_assets.prepare_visual_assets(
                self.job,
                component_adapters=self.component_adapters,
                segment_ffmpeg_runner=valid_segment,
                segment_probe=self._probe,
                segment_frame_extractor=self._frame,
            )

        probe = segment_render._default_probe(track)
        self.assertTrue(segment_render._probe_matches(probe, 288))
        self.assertEqual((probe["width"], probe["height"]), (1080, 1920))


if __name__ == "__main__":
    unittest.main()

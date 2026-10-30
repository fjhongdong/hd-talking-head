from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from edit.hd.tools import broll_component_executor as executor

ROOT = Path(__file__).resolve().parents[3]


class _Text(str):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class _Job:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.job_dir = root / "job"
        self.job_dir.mkdir()
        self.job_id = "job-001"


def _window() -> dict[str, object]:
    return {
        "start_frame": 0,
        "end_frame": 48,
        "z_index": 0,
        "layout_slot": "main",
        "opacity": 1.0,
        "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
    }


def _common(component_id: str, kind: str, media_type: str) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": "base",
        "executor": f"approved:{kind}",
        "media_type": media_type,
        "render_window": _window(),
        "artifact_contract": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "alpha": kind == "code_generated",
        },
    }


def _material_component(
    kind: str,
    *,
    relative: str,
    source_sha: str,
    component_id: str | None = None,
) -> dict[str, object]:
    component = _common(component_id or kind, kind, "video")
    if kind == "local_material":
        component.update(
            material_id="material-001", job_path=relative, sha256=source_sha
        )
    elif kind == "official_material":
        component.update(
            source_id="official-001",
            publisher="Example Institute",
            source_url="https://example.org/report",
            snapshot_path=relative,
            fetched_at="2026-08-31T12:00:00+08:00",
            sha256=source_sha,
        )
    elif kind == "external_stock":
        key = "a" * 64
        component.update(
            provider="Pexels",
            provider_asset_id="101",
            author="Example Author",
            asset_page="https://www.pexels.com/video/101",
            job_path=f"stock/{key[:2]}/{key}.mp4",
            license_snapshot=f"stock/{key[:2]}/{key}.license.json",
            downloaded_at="2026-08-31T12:00:00Z",
            sha256=source_sha,
        )
    else:
        raise AssertionError(kind)
    return component


def _ai_component(payload: bytes, *, component_id: str = "ai") -> dict[str, object]:
    component = _common(component_id, "ai_generated", "video")
    component.update(
        provider="xAI",
        model="grok-imagine-video",
        endpoint_id="video-generation",
        prompt_sha256="5" * 64,
        generation_id="generation-001",
        sha256=_sha256(payload),
    )
    return component


def _code_component(
    brief: bytes,
    *,
    dependency_id: str = "html-video",
    component_id: str = "code",
) -> dict[str, object]:
    renderer = "HyperFrames" if dependency_id == "html-video" else "Remotion"
    entrypoint = "render.py" if dependency_id == "html-video" else "skill.py"
    component = _common(component_id, "code_generated", "animation")
    component.update(
        producer_type="dependency",
        dependency_id=dependency_id,
        entrypoint=entrypoint,
        producer_version="approved-version",
        brief_sha256=_sha256(brief),
        invocation_record={
            "argv": ["FORGED-AND-MUST-NEVER-RUN", entrypoint],
            "exit_code": 0,
            "template_request": {"semantic_family": "explanation", "information_units": 3,
                                 "numeric_values": [], "numeric_scale": "not_applicable"},
        },
        primary_renderer=renderer,
        renderer_version="approved-renderer",
        template_origin="custom_fallback",
        template_id="executor-fixture",
        template_version="1",
        verification_id="7" * 64,
        adaptation_level="structural",
        source_entrypoint="templates/executor-fixture.html",
        source_sha256="8" * 64,
        sample_sha256="9" * 64,
        semantic_families=["explanation"],
        capacity={"min_units": 1, "max_units": 7},
    )
    return component


def _recipe(components: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 7,
        "mode": "single" if len(components) == 1 else "hybrid",
        "composition": {
            "family": (
                "single_full_frame"
                if len(components) == 1
                else "evidence_with_data_overlay"
            ),
            "presenter_mode": "bottom_window",
            "reading_order": [component["component_id"] for component in components],
            "component_dependencies": [],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }


def _request(component: dict[str, object]) -> executor.ComponentExecutionRequest:
    return executor.ComponentExecutionRequest(
        recipe=_recipe([component]), component_id=str(component["component_id"])
    )


def _probe(
    _path: Path, media_type: str, contract: object
) -> dict[str, object]:
    if media_type == "image":
        container = "png"
        codec = "png"
        pixel_format = "rgba" if contract["alpha"] else "rgb24"
    elif contract["alpha"]:
        container = "mov"
        codec = "prores_ks"
        pixel_format = "yuva444p10le"
    else:
        container = "mp4"
        codec = "h264"
        pixel_format = "yuv420p"
    return {
        "media_type": media_type,
        "container": container,
        "codec": codec,
        "pixel_format": pixel_format,
        "alpha": contract["alpha"],
        "width": 1080,
        "height": 1920,
        "fps": 24 if media_type == "video" else None,
        "frame_count": 48 if media_type == "video" else 1,
        "duration": 2.0 if media_type == "video" else None,
    }


def _artifact_probe() -> executor.ArtifactProbe:
    return executor.ArtifactProbe(
        probe_id="approved-media-probe",
        probe_version="1.0.0",
        probe=_probe,
    )


class _RecordingKindAdapter:
    def __init__(self, payload: bytes, *, failure: BaseException | None = None) -> None:
        self.payload = payload
        self.failure = failure
        self.calls: list[executor.AdapterContext] = []

    def invoke(self, context: executor.AdapterContext) -> executor.AdapterResult:
        self.calls.append(context)
        if self.failure is not None:
            raise self.failure
        context.staging_path.write_bytes(self.payload)
        return executor.AdapterResult(
            invocation_evidence={
                "adapter_id": context.kind,
                "actual_output_job_path": context.staging_job_path,
            },
            qa={"passed": True, "checks": ["adapter_completed"]},
        )

    def binding(self, kind: str, name: str) -> executor.KindAdapter:
        return executor.KindAdapter(
            kind=kind,
            approved_executor=f"approved:{kind}",
            adapter_id=name,
            adapter_version="1.0.0",
            artifact_media_type="video",
            invoke=self.invoke,
            provider="xAI" if kind == "ai_generated" else None,
            model="grok-imagine-video" if kind == "ai_generated" else None,
            endpoint_id="video-generation" if kind == "ai_generated" else None,
        )


def _write_job_file(job: _Job, relative: str, payload: bytes) -> Path:
    path = job.job_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _write_stock_license(
    job: _Job, component: dict[str, object], payload: bytes
) -> Path:
    license_path = job.job_dir / str(component["license_snapshot"])
    license_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "idempotency_key": "a" * 64,
        "search_generation": "search-001",
        "snapshot_sha256": "b" * 64,
        "query_sha256": "c" * 64,
        "provider": component["provider"],
        "provider_asset_id": component["provider_asset_id"],
        "author": component["author"],
        "asset_page": component["asset_page"],
        "license_name": "Pexels License",
        "license_version": "pexels-license-v1",
        "downloaded_at": component["downloaded_at"],
        "byte_count": len(payload),
        "sha256": component["sha256"],
        "job_path": component["job_path"],
        "license_snapshot": component["license_snapshot"],
    }
    license_path.write_bytes(_canonical(record) + b"\n")
    media = (job.job_dir / str(component["job_path"])).stat()
    license_metadata = license_path.stat()
    key = record["idempotency_key"]
    nonce = "d" * 32
    receipt = {
        "schema_version": 1,
        "state": "published",
        "idempotency_key": key,
        "nonce": nonce,
        "provider": record["provider"],
        "provider_asset_id": record["provider_asset_id"],
        "search_generation": record["search_generation"],
        "snapshot_sha256": record["snapshot_sha256"],
        "query_sha256": record["query_sha256"],
        "staging_job_path": f"stock/{key[:2]}/.{key}.{nonce}.staging.mp4",
        "planned_job_path": record["job_path"],
        "planned_license_snapshot": record["license_snapshot"],
        "license_staging_job_path": (
            f"stock/{key[:2]}/.{key}.{nonce}.license.staging.json"
        ),
        "media_type": "video",
        "format": "mp4",
        "mime_type": "video/mp4",
        "expected_identity": [
            media.st_dev,
            media.st_ino,
            media.st_mode,
            media.st_nlink,
            0,
            0,
            0,
        ],
        "downloaded_at": record["downloaded_at"],
        "byte_count": record["byte_count"],
        "sha256": record["sha256"],
        "actual_width": 1080,
        "actual_height": 1920,
        "dimensions_source": "provider_variant",
        "license_record": record,
        "license_sha256": _sha256(_canonical(record) + b"\n"),
        "license_identity": [
            license_metadata.st_dev,
            license_metadata.st_ino,
            license_metadata.st_mode,
        ],
    }
    receipt_path = job.job_dir / f"stock/{key[:2]}/{key}.download.json"
    receipt_path.write_bytes(_canonical(receipt) + b"\n")
    return license_path


def _kind_registry(
    adapters: dict[str, _RecordingKindAdapter]
) -> dict[str, object]:
    return {
        **{
            kind: adapter.binding(kind, f"{kind}-adapter")
            for kind, adapter in adapters.items()
        },
        "artifact_probe": _artifact_probe(),
    }


class ComponentExecutorDispatchTests(unittest.TestCase):
    def test_adapter_contract_uses_request_only_value_api(self) -> None:
        for adapter_type in (
            executor.KindAdapter,
            executor.ReferenceProcessAdapter,
            executor.SkillInvocationAdapter,
        ):
            field_names = adapter_type.__dataclass_fields__
            self.assertIn("request_only_values", field_names)

        self.assertTrue(hasattr(executor, "_non_record_field"))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.job = _Job(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _replace_output_chain(
        self, target: str, label: str
    ) -> tuple[Path, Path, Path]:
        visible = (
            self.job.job_dir
            if target == "job"
            else self.job.job_dir / "08-visual-assets"
        )
        moved = self.root / f"{label}-{target}-pinned"
        outside = self.root / f"{label}-{target}-replacement"
        outside.mkdir()
        visible.rename(moved)
        visible.symlink_to(outside, target_is_directory=True)
        return visible, moved, outside

    def _restore_output_chain(
        self, visible: Path, moved: Path, outside: Path
    ) -> None:
        self.assertEqual(list(outside.iterdir()), [])
        visible.unlink()
        moved.rename(visible)
        outside.rmdir()

    @staticmethod
    def _moved_artifact_paths(
        moved: Path, target: str, component_id: str
    ) -> tuple[Path, Path]:
        relative_parent = Path("components/seg-001")
        if target == "job":
            relative_parent = Path("08-visual-assets") / relative_parent
        final = relative_parent / f"{component_id}-r7.mp4"
        journal = relative_parent / f".{component_id}-r7.transaction.json"
        return moved / final, moved / journal

    def test_raw_component_is_not_compatibly_accepted_and_has_zero_side_effects(self) -> None:
        component = _ai_component(b"generated")
        spies = {
            kind: _RecordingKindAdapter(b"must-not-run")
            for kind in (
                "local_material",
                "official_material",
                "external_stock",
                "ai_generated",
            )
        }

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job, component, adapters=_kind_registry(spies)
            )

        self.assertEqual(caught.exception.error_code, "BROLL_SCHEMA_INVALID")
        self.assertEqual(sum(len(item.calls) for item in spies.values()), 0)
        self.assertEqual(list(self.job.job_dir.iterdir()), [])

    def test_invalid_complete_recipe_stops_every_adapter_before_side_effects(self) -> None:
        component = _ai_component(b"generated")
        request = _request(component)
        request.recipe["schema_version"] = 1
        spies = {
            kind: _RecordingKindAdapter(b"must-not-run")
            for kind in (
                "local_material",
                "official_material",
                "external_stock",
                "ai_generated",
            )
        }

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job, request, adapters=_kind_registry(spies)
            )

        self.assertEqual(caught.exception.error_code, "BROLL_SCHEMA_INVALID")
        self.assertEqual(sum(len(item.calls) for item in spies.values()), 0)
        self.assertEqual(list(self.job.job_dir.iterdir()), [])

    def test_kind_adapter_string_bindings_require_exact_nonempty_strings(self) -> None:
        output = b"unused"
        fields = (
            "kind",
            "approved_executor",
            "adapter_id",
            "adapter_version",
            "artifact_media_type",
            "provider",
            "model",
            "endpoint_id",
        )
        for field in fields:
            with self.subTest(field=field):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                job = _Job(Path(temporary.name).resolve())
                component = _ai_component(
                    output, component_id=f"exact-kind-{field}"
                )
                recording = _RecordingKindAdapter(output)
                base = recording.binding("ai_generated", "ai")
                value = getattr(base, field)
                adapter = executor.KindAdapter(
                    **{**base.__dict__, field: _Text(value)}
                )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        job,
                        _request(component),
                        adapters={
                            "ai_generated": adapter,
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code,
                    "BROLL_PROVIDER_UNCONNECTED",
                )
                self.assertEqual(recording.calls, [])
                self.assertFalse((job.job_dir / "08-visual-assets").exists())

    def test_five_kinds_dispatch_only_to_their_own_adapter(self) -> None:
        output = b"normalized-component-output"
        source = b"frozen-source"
        brief = b'{"brief":"approved"}'
        components: dict[str, dict[str, object]] = {}
        for kind in ("local_material", "official_material", "external_stock"):
            relative = f"inputs/{kind}.mp4"
            components[kind] = _material_component(
                kind, relative=relative, source_sha=_sha256(source)
            )
            path_field = "snapshot_path" if kind == "official_material" else "job_path"
            _write_job_file(self.job, str(components[kind][path_field]), source)
        _write_stock_license(self.job, components["external_stock"], source)
        components["ai_generated"] = _ai_component(output)

        for selected_kind in (
            "local_material",
            "official_material",
            "external_stock",
            "ai_generated",
        ):
            with self.subTest(kind=selected_kind):
                spies = {
                    kind: _RecordingKindAdapter(output)
                    for kind in (
                        "local_material",
                        "official_material",
                        "external_stock",
                        "ai_generated",
                    )
                }
                artifact = executor.execute_component(
                    self.job,
                    _request(copy.deepcopy(components[selected_kind])),
                    adapters=_kind_registry(spies),
                )
                self.assertEqual(artifact.kind, selected_kind)
                self.assertEqual(len(spies[selected_kind].calls), 1)
                self.assertEqual(
                    sum(len(item.calls) for item in spies.values()), 1
                )

        dependency = self._working_code_adapter(brief, output)
        artifact = executor.execute_component(
            self.job,
            _request(_code_component(brief)),
            adapters={
                "code_generated": {"html-video": dependency},
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertEqual(artifact.kind, "code_generated")

    def test_success_artifact_is_strict_immutable_and_recipe_bound(self) -> None:
        output = b"generated"
        component = _ai_component(output)
        request = _request(component)
        adapter = _RecordingKindAdapter(output)
        artifact = executor.execute_component(
            self.job,
            request,
            adapters={
                "ai_generated": adapter.binding("ai_generated", "ai"),
                "artifact_probe": _artifact_probe(),
            },
        )

        expected_input = _sha256(
            _canonical(
                {
                    "recipe": request.recipe,
                    "component_id": request.component_id,
                }
            )
        )
        self.assertEqual(artifact.schema_version, 1)
        self.assertEqual(artifact.status, "success")
        self.assertEqual(artifact.job_id, self.job.job_id)
        self.assertEqual(artifact.segment_id, "seg-001")
        self.assertEqual(artifact.component_id, "ai")
        self.assertEqual(artifact.strategy_revision, 7)
        self.assertEqual(artifact.input_sha256, expected_input)
        self.assertEqual(artifact.byte_count, len(output))
        self.assertEqual(artifact.output_sha256, _sha256(output))
        self.assertIsNone(artifact.error_code)
        self.assertFalse(Path(artifact.job_path).is_absolute())
        self.assertEqual(
            (self.job.job_dir / artifact.job_path).read_bytes(), output
        )
        serialized = json.loads(json.dumps(dict(artifact), sort_keys=True))
        self.assertEqual(serialized["output_sha256"], artifact.output_sha256)
        self.assertEqual(serialized["qa"]["passed"], True)
        self.assertEqual(serialized["media_probe"]["media_type"], "video")
        self.assertEqual(dict(artifact.render_window), _window())
        self.assertEqual(artifact.z_index, 0)
        self.assertEqual(artifact.layout_slot, "main")
        self.assertEqual(artifact.opacity, 1.0)
        self.assertEqual(dict(artifact.safe_zone), _window()["safe_zone"])
        self.assertEqual(dict(artifact.artifact_contract), component["artifact_contract"])
        self.assertEqual(artifact.source_media_type, "video")
        self.assertEqual(artifact.artifact_media_type, "video")
        with self.assertRaises(FrozenInstanceError):
            artifact.status = "forged"
        with self.assertRaises(TypeError):
            artifact.qa["passed"] = False
        with self.assertRaises(TypeError):
            artifact.invocation_evidence["adapter_id"] = "forged"

    def test_integer_opacity_is_normalized_before_adapter_and_receipt(self) -> None:
        for opacity in (0, 1):
            with self.subTest(opacity=opacity):
                output = f"opacity-{opacity}".encode()
                component = _ai_component(
                    output, component_id=f"opacity-{opacity}"
                )
                component["render_window"]["opacity"] = opacity
                adapter = _RecordingKindAdapter(output)

                artifact = executor.execute_component(
                    self.job,
                    _request(component),
                    adapters={
                        "ai_generated": adapter.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )

                self.assertEqual(len(adapter.calls), 1)
                self.assertIs(type(artifact.opacity), float)
                self.assertEqual(artifact.opacity, float(opacity))
                self.assertIs(type(artifact.render_window["opacity"]), float)
                receipt = self.job.job_dir / (
                    "08-visual-assets/components/seg-001/"
                    f".opacity-{opacity}-r7.transaction.json"
                )
                record = json.loads(receipt.read_text())
                self.assertIs(
                    type(record["artifact"]["render_window"]["opacity"]),
                    float,
                )

    def test_kind_adapter_non_record_fields_are_rejected_without_publish(self) -> None:
        output = b"generated"
        request_only_value = "PROVIDER-REQUEST-ONLY-VALUE"

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            context.staging_path.write_bytes(output)
            return executor.AdapterResult(
                invocation_evidence={"authorization": request_only_value},
                qa={"provider_debug": request_only_value, "passed": True},
            )

        adapter = executor.KindAdapter(
            kind="ai_generated",
            approved_executor="approved:ai_generated",
            adapter_id="ai",
            adapter_version="1",
            artifact_media_type="video",
            invoke=invoke,
            provider="xAI",
            model="grok-imagine-video",
            endpoint_id="video-generation",
            request_only_values=(request_only_value,),
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(output)),
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")

    def test_registered_request_only_values_are_filtered_from_success_artifact(self) -> None:
        output = b"generated"
        request_only_value = "provider-request-only-value"

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            context.staging_path.write_bytes(output)
            return executor.AdapterResult(
                invocation_evidence={"provider_message": request_only_value},
                qa={"passed": True, "checks": ["adapter_completed"]},
            )

        base = _RecordingKindAdapter(output).binding("ai_generated", "ai")
        adapter = executor.KindAdapter(
            **{
                **base.__dict__,
                "invoke": invoke,
                "request_only_values": (request_only_value,),
            }
        )
        artifact = executor.execute_component(
            self.job,
            _request(_ai_component(output)),
            adapters={
                "ai_generated": adapter,
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertNotIn(request_only_value, json.dumps(dict(artifact)))
        self.assertEqual(
            artifact.invocation_evidence["adapter_record"]["provider_message"],
            "[FILTERED]",
        )

    def test_code_evidence_role_is_truth_conflict_before_dependency_invocation(self) -> None:
        brief = b"approved"
        component = _code_component(brief)
        component["semantic_role"] = "evidence"
        marker = self.root / "must-not-exist"
        dependency = self._working_code_adapter(brief, b"output", marker=marker)

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "code_generated": {"html-video": dependency},
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_TRUTH_CONFLICT")
        self.assertFalse(marker.exists())

    def test_each_kind_failure_never_calls_another_kind(self) -> None:
        source = b"source"
        output = b"generated"
        components = {
            "local_material": _material_component(
                "local_material",
                relative="inputs/local.mp4",
                source_sha=_sha256(source),
            ),
            "official_material": _material_component(
                "official_material",
                relative="inputs/official.mp4",
                source_sha=_sha256(source),
            ),
            "external_stock": _material_component(
                "external_stock",
                relative="inputs/stock.mp4",
                source_sha=_sha256(source),
            ),
            "ai_generated": _ai_component(output),
        }
        _write_job_file(self.job, str(components["local_material"]["job_path"]), source)
        _write_job_file(
            self.job, str(components["official_material"]["snapshot_path"]), source
        )
        _write_job_file(self.job, str(components["external_stock"]["job_path"]), source)
        _write_stock_license(self.job, components["external_stock"], source)

        for selected_kind, expected_code in (
            ("local_material", "BROLL_COMPOSITE_FAILED"),
            ("official_material", "BROLL_COMPOSITE_FAILED"),
            ("external_stock", "BROLL_DOWNLOAD_REJECTED"),
            ("ai_generated", "BROLL_GENERATION_FAILED"),
        ):
            with self.subTest(kind=selected_kind):
                spies = {
                    kind: _RecordingKindAdapter(
                        b"unused",
                        failure=(
                            RuntimeError("selected failure")
                            if kind == selected_kind
                            else None
                        ),
                    )
                    for kind in components
                }
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    executor.execute_component(
                        self.job,
                        _request(copy.deepcopy(components[selected_kind])),
                        adapters=_kind_registry(spies),
                    )
                self.assertEqual(caught.exception.error_code, expected_code)
                self.assertEqual(
                    caught.exception.allowed_actions,
                    ("retry_same_strategy", "replan_visual_direction"),
                )
                self.assertEqual(len(spies[selected_kind].calls), 1)
                self.assertEqual(sum(len(item.calls) for item in spies.values()), 1)

    def test_code_failure_never_calls_any_material_stock_or_ai_adapter(self) -> None:
        brief = b"approved"
        dependency = self._working_code_adapter(brief, b"unused")
        entrypoint = dependency.dependency_root / dependency.entrypoint
        entrypoint.write_text(
            "raise SystemExit(19)\n", encoding="utf-8"
        )
        dependency = executor.ReferenceProcessAdapter(
            **{
                **dependency.__dict__,
                "entrypoint_sha256": _sha256(entrypoint.read_bytes()),
            }
        )
        spies = {
            kind: _RecordingKindAdapter(b"must-not-run")
            for kind in (
                "local_material",
                "official_material",
                "external_stock",
                "ai_generated",
            )
        }
        registry = _kind_registry(spies)
        registry["code_generated"] = {"html-video": dependency}

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_code_component(brief)),
                adapters=registry,
            )

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
        self.assertEqual(sum(len(item.calls) for item in spies.values()), 0)

    def test_stable_error_code_matrix(self) -> None:
        self.assertEqual(
            executor.ERROR_CODES,
            frozenset(
                {
                    "BROLL_SCHEMA_INVALID",
                    "BROLL_TRUTH_CONFLICT",
                    "BROLL_PROVIDER_UNCONNECTED",
                    "BROLL_DOWNLOAD_REJECTED",
                    "BROLL_DEPENDENCY_UNBOUND",
                    "BROLL_GENERATION_FAILED",
                    "BROLL_RENDER_FAILED",
                    "BROLL_COMPOSITE_FAILED",
                }
            ),
        )

    def test_adapter_binding_preflight_is_complete_before_staging_io(self) -> None:
        output = b"generated"
        recorder = _RecordingKindAdapter(output)
        valid = recorder.binding("ai_generated", "ai-adapter")
        invalid = (
            executor.KindAdapter(**{**valid.__dict__, "kind": "local_material"}),
            executor.KindAdapter(
                **{**valid.__dict__, "approved_executor": "other-runtime"}
            ),
            executor.KindAdapter(**{**valid.__dict__, "provider": "other-provider"}),
            executor.KindAdapter(**{**valid.__dict__, "model": "other-model"}),
            executor.KindAdapter(**{**valid.__dict__, "endpoint_id": "other-endpoint"}),
        )
        for adapter in invalid:
            with self.subTest(adapter=adapter):
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    executor.execute_component(
                        self.job,
                        _request(_ai_component(output)),
                        adapters={
                            "ai_generated": adapter,
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_PROVIDER_UNCONNECTED"
                )
                self.assertEqual(recorder.calls, [])
                self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_kind_callback_receives_frozen_inputs_and_recipe_mutation_is_detected(self) -> None:
        output = b"generated"
        request = _request(_ai_component(output))

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            with self.assertRaises(TypeError):
                context.component["executor"] = "forged"
            request.recipe["components"][0]["artifact_contract"]["width"] = 720
            context.staging_path.write_bytes(output)
            return executor.AdapterResult(
                invocation_evidence={"adapter_id": "ai"},
                qa={"passed": True, "checks": ["adapter_completed"]},
            )

        adapter = executor.KindAdapter(
            **{
                **_RecordingKindAdapter(output)
                .binding("ai_generated", "ai")
                .__dict__,
                "invoke": invoke,
            }
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_SCHEMA_INVALID")
        self.assertFalse(
            (self.job.job_dir / "08-visual-assets/components/seg-001/ai-r7.mp4").exists()
        )

    def test_probe_receives_frozen_contract_and_detects_post_adapter_recipe_mutation(self) -> None:
        output = b"generated"
        request = _request(_ai_component(output))
        adapter = _RecordingKindAdapter(output).binding("ai_generated", "ai")

        def probe(path: Path, media_type: str, contract: object) -> dict[str, object]:
            with self.assertRaises(TypeError):
                contract["fps"] = 30
            request.recipe["components"][0]["artifact_contract"]["fps"] = 30
            return _probe(path, media_type, contract)

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": executor.ArtifactProbe(
                        probe_id="mutating-probe",
                        probe_version="1",
                        probe=probe,
                    ),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_SCHEMA_INVALID")

    def test_adapter_result_requires_strict_passing_qa_and_canonical_json(self) -> None:
        output = b"generated"
        invalid_results = (
            executor.AdapterResult(
                invocation_evidence={"ok": True},
                qa={"passed": False, "checks": ["failed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={"path": Path("not-json")},
                qa={"passed": True, "checks": ["adapter_completed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={"value": float("nan")},
                qa={"passed": True, "checks": ["adapter_completed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={"authorization": "request-only"},
                qa={"passed": True, "checks": ["adapter_completed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={
                    "job_path": str(self.job.job_dir / "request-only")
                },
                qa={"passed": True, "checks": ["adapter_completed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={"oversized": "x" * (70 * 1024)},
                qa={"passed": True, "checks": ["adapter_completed"]},
            ),
            executor.AdapterResult(
                invocation_evidence={"ok": True},
                qa={"passed": True, "checks": ["ok"], "extra": True},
            ),
        )
        for result in invalid_results:
            with self.subTest(result=result):
                def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
                    context.staging_path.write_bytes(output)
                    return result

                adapter = executor.KindAdapter(
                    **{
                        **_RecordingKindAdapter(output)
                        .binding("ai_generated", "ai")
                        .__dict__,
                        "invoke": invoke,
                    }
                )
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    executor.execute_component(
                        self.job,
                        _request(_ai_component(output)),
                        adapters={
                            "ai_generated": adapter,
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")

    def test_document_and_webpage_sources_are_normalized_to_composable_video(self) -> None:
        source = b"source-document"
        output = b"normalized-video"
        for media_type in ("document", "webpage"):
            with self.subTest(media_type=media_type):
                component = _material_component(
                    "local_material",
                    relative=f"inputs/source-{media_type}.bin",
                    source_sha=_sha256(source),
                    component_id=f"source-{media_type}",
                )
                component["media_type"] = media_type
                _write_job_file(self.job, str(component["job_path"]), source)
                adapter = _RecordingKindAdapter(output)
                artifact = executor.execute_component(
                    self.job,
                    _request(component),
                    adapters={
                        "local_material": adapter.binding(
                            "local_material", "normalizer"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(artifact.source_media_type, media_type)
                self.assertEqual(artifact.artifact_media_type, "video")
                self.assertEqual(artifact.media_probe["container"], "mp4")

    def test_missing_kind_adapter_is_provider_unconnected_without_fallback(self) -> None:
        output = b"generated"
        other = _RecordingKindAdapter(output)
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(output)),
                adapters={
                    "local_material": other.binding("local_material", "local"),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_PROVIDER_UNCONNECTED")
        self.assertEqual(other.calls, [])

    def test_stock_requires_exact_published_license_before_adapter_call(self) -> None:
        source = b"stock"
        component = _material_component(
            "external_stock",
            relative="stock/aa/asset.mp4",
            source_sha=_sha256(source),
        )
        _write_job_file(self.job, str(component["job_path"]), source)
        license_path = _write_stock_license(self.job, component, source)
        parsed = json.loads(license_path.read_text())
        parsed["provider_asset_id"] = "forged"
        license_path.write_bytes(_canonical(parsed) + b"\n")
        adapter = _RecordingKindAdapter(b"normalized")

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "external_stock": adapter.binding("external_stock", "stock"),
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_DOWNLOAD_REJECTED")
        self.assertEqual(adapter.calls, [])

    def test_stock_requires_published_task6_receipt_before_adapter_call(self) -> None:
        source = b"stock"
        component = _material_component(
            "external_stock",
            relative="ignored.mp4",
            source_sha=_sha256(source),
        )
        _write_job_file(self.job, str(component["job_path"]), source)
        _write_stock_license(self.job, component, source)
        receipt = self.job.job_dir / (
            "stock/aa/" + "a" * 64 + ".download.json"
        )
        record = json.loads(receipt.read_text())
        record["state"] = "complete"
        receipt.write_bytes(_canonical(record) + b"\n")
        adapter = _RecordingKindAdapter(b"normalized")

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "external_stock": adapter.binding("external_stock", "stock"),
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_DOWNLOAD_REJECTED")
        self.assertEqual(adapter.calls, [])

    def test_material_hash_change_is_rejected_before_adapter_call(self) -> None:
        component = _material_component(
            "local_material",
            relative="inputs/local.mp4",
            source_sha=_sha256(b"approved"),
        )
        _write_job_file(self.job, "inputs/local.mp4", b"changed")
        adapter = _RecordingKindAdapter(b"normalized")

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "local_material": adapter.binding("local_material", "local"),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_COMPOSITE_FAILED")
        self.assertEqual(adapter.calls, [])

    def test_failed_execution_never_half_publishes_or_reuses_stale_final(self) -> None:
        output = b"expected"
        component = _ai_component(output)
        final = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/ai-r7.mp4"
        )
        final.parent.mkdir(parents=True)
        final.write_bytes(b"stale")
        adapter = _RecordingKindAdapter(output)

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "ai_generated": adapter.binding("ai_generated", "ai"),
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(final.read_bytes(), b"stale")
        self.assertEqual(
            list(self.job.job_dir.rglob("*.staging.*")), []
        )

    def test_publish_fsync_failure_rolls_back_executor_owned_final(self) -> None:
        output = b"generated"
        adapter = _RecordingKindAdapter(output)
        final = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/ai-r7.mp4"
        )
        real_fsync = executor.os.fsync
        calls = 0

        def fail_second_directory_fsync(descriptor: int) -> None:
            nonlocal calls
            metadata = os.fstat(descriptor)
            if stat.S_ISDIR(metadata.st_mode):
                calls += 1
                if calls == 2:
                    raise OSError("injected publication fsync failure")
            real_fsync(descriptor)

        with mock.patch.object(executor.os, "fsync", side_effect=fail_second_directory_fsync):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                executor.execute_component(
                    self.job,
                    _request(_ai_component(output)),
                    adapters={
                        "ai_generated": adapter.binding("ai_generated", "ai"),
                        "artifact_probe": _artifact_probe(),
                    },
                )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertFalse(final.exists())

    def test_staging_cleanup_failure_never_reports_success(self) -> None:
        output = b"generated"
        adapter = _RecordingKindAdapter(output)
        final = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/ai-r7.mp4"
        )

        with mock.patch.object(
            executor,
            "_remove_tree_at",
            side_effect=OSError("injected cleanup failure"),
        ):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                executor.execute_component(
                    self.job,
                    _request(_ai_component(output)),
                    adapters={
                        "ai_generated": adapter.binding("ai_generated", "ai"),
                        "artifact_probe": _artifact_probe(),
                    },
                )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertFalse(final.exists())

        recovered = executor.execute_component(
            self.job,
            _request(_ai_component(output)),
            adapters={
                "ai_generated": adapter.binding("ai_generated", "ai"),
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertEqual((self.job.job_dir / recovered.job_path).read_bytes(), output)

    def test_cleanup_failure_never_deletes_existing_final(self) -> None:
        output = b"generated"
        adapter = _RecordingKindAdapter(output)
        final = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/ai-r7.mp4"
        )
        final.parent.mkdir(parents=True)
        final.write_bytes(b"existing-final")

        with mock.patch.object(
            executor,
            "_remove_tree_at",
            side_effect=OSError("injected cleanup failure"),
        ):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                executor.execute_component(
                    self.job,
                    _request(_ai_component(output)),
                    adapters={
                        "ai_generated": adapter.binding("ai_generated", "ai"),
                        "artifact_probe": _artifact_probe(),
                    },
                )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(final.read_bytes(), b"existing-final")

    def test_rejected_additional_hardlink_staging_never_deletes_source(self) -> None:
        expected = b"generated"
        source_copy = self.root / "source-copy.mp4"
        source_copy.write_bytes(expected)

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            os.link(source_copy, context.staging_path)
            return executor.AdapterResult(
                invocation_evidence={"adapter": "additional-hardlink"},
                qa={"passed": True, "checks": ["adapter_completed"]},
            )

        adapter = executor.KindAdapter(
            kind="ai_generated",
            approved_executor="approved:ai_generated",
            adapter_id="ai",
            adapter_version="1",
            artifact_media_type="video",
            invoke=invoke,
            provider="xAI",
            model="grok-imagine-video",
            endpoint_id="video-generation",
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(expected)),
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(source_copy.read_bytes(), expected)
        self.assertGreaterEqual(source_copy.stat().st_nlink, 1)

    def test_job_output_symlink_is_rejected_before_callback_with_zero_external_write(self) -> None:
        outside = self.root / "outside-output"
        outside.mkdir()
        (self.job.job_dir / "08-visual-assets").symlink_to(
            outside, target_is_directory=True
        )
        adapter = _RecordingKindAdapter(b"generated")

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(b"generated")),
                adapters={
                    "ai_generated": adapter.binding("ai_generated", "ai"),
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(adapter.calls, [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_output_chain_replaced_during_callback_never_publishes_through_new_path(self) -> None:
        output = b"generated"
        outside = self.root / "concurrent-replacement"
        outside.mkdir()

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            context.staging_path.write_bytes(output)
            visual_root = self.job.job_dir / "08-visual-assets"
            moved = self.job.job_dir / "08-moved"
            visual_root.rename(moved)
            visual_root.symlink_to(outside, target_is_directory=True)
            return executor.AdapterResult(
                invocation_evidence={"completed": True},
                qa={"passed": True, "checks": ["generated"]},
            )

        base = _RecordingKindAdapter(output).binding("ai_generated", "ai")
        adapter = executor.KindAdapter(**{**base.__dict__, "invoke": invoke})
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(output)),
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(list(outside.iterdir()), [])

    def test_job_ancestor_replacement_during_callback_is_detected_before_publish(self) -> None:
        output = b"generated"
        moved = self.root.with_name(self.root.name + "-moved")

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            context.staging_path.write_bytes(output)
            self.root.rename(moved)
            self.root.symlink_to(moved, target_is_directory=True)
            return executor.AdapterResult(
                invocation_evidence={"completed": True},
                qa={"passed": True, "checks": ["generated"]},
            )

        base = _RecordingKindAdapter(output).binding("ai_generated", "ai")
        try:
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                executor.execute_component(
                    self.job,
                    _request(_ai_component(output)),
                    adapters={
                        "ai_generated": executor.KindAdapter(
                            **{**base.__dict__, "invoke": invoke}
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
            self.assertEqual(
                caught.exception.error_code, "BROLL_GENERATION_FAILED"
            )
            self.assertFalse(
                (moved / "job/08-visual-assets/components/seg-001/ai-r7.mp4").exists()
            )
        finally:
            if self.root.is_symlink():
                self.root.unlink()
            if moved.exists():
                moved.rename(self.root)

    def test_nonce_replacement_is_rejected_without_deleting_unrelated_or_moved_content(self) -> None:
        output = b"generated"
        preserved: dict[str, Path] = {}

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            context.staging_path.write_bytes(output)
            nonce = self.job.job_dir.joinpath(
                *Path(context.staging_job_path).parts
            ).parent
            moved = nonce.with_name(nonce.name + ".moved")
            nonce.rename(moved)
            nonce.mkdir()
            unrelated = nonce / "unrelated.txt"
            unrelated.write_text("keep")
            preserved.update(moved=moved, unrelated=unrelated)
            return executor.AdapterResult(
                invocation_evidence={"completed": True},
                qa={"passed": True, "checks": ["generated"]},
            )

        base = _RecordingKindAdapter(output).binding("ai_generated", "ai")
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(output)),
                adapters={
                    "ai_generated": executor.KindAdapter(
                        **{**base.__dict__, "invoke": invoke}
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(preserved["unrelated"].read_text(), "keep")
        self.assertTrue(preserved["moved"].exists())

    def test_material_callback_gets_verified_staged_snapshot_not_mutable_source(self) -> None:
        approved = b"approved-source"
        normalized = b"normalized"
        component = _material_component(
            "local_material",
            relative="inputs/local.mp4",
            source_sha=_sha256(approved),
        )
        original = _write_job_file(self.job, "inputs/local.mp4", approved)

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            self.assertIsNotNone(context.source_path)
            self.assertNotEqual(context.source_path, original)
            original.write_bytes(b"changed-after-snapshot")
            self.assertEqual(context.source_path.read_bytes(), approved)
            context.staging_path.write_bytes(normalized)
            return executor.AdapterResult(
                invocation_evidence={"snapshot": True},
                qa={"passed": True, "checks": ["snapshot_consumed"]},
            )

        binding = executor.KindAdapter(
            **{
                **_RecordingKindAdapter(normalized)
                .binding("local_material", "local")
                .__dict__,
                "invoke": invoke,
            }
        )
        artifact = executor.execute_component(
            self.job,
            _request(component),
            adapters={
                "local_material": binding,
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertEqual(artifact.source_media_type, "video")

    def test_source_replaced_after_task5_resolution_is_rejected_before_callback(self) -> None:
        approved = b"approved-source"
        component = _material_component(
            "local_material",
            relative="inputs/local.mp4",
            source_sha=_sha256(approved),
        )
        source = _write_job_file(self.job, "inputs/local.mp4", approved)
        adapter = _RecordingKindAdapter(b"normalized")
        real_resolve = executor.broll_media.resolve_recipe_media

        def replace_after_resolve(*args: object, **kwargs: object) -> object:
            resolved = real_resolve(*args, **kwargs)
            source.unlink()
            source.write_bytes(b"replacement")
            return resolved

        with mock.patch.object(
            executor.broll_media,
            "resolve_recipe_media",
            side_effect=replace_after_resolve,
        ):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                executor.execute_component(
                    self.job,
                    _request(component),
                    adapters={
                        "local_material": adapter.binding(
                            "local_material", "local"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
        self.assertEqual(caught.exception.error_code, "BROLL_COMPOSITE_FAILED")
        self.assertEqual(adapter.calls, [])

    def test_published_same_input_replays_with_zero_adapter_and_probe_calls(self) -> None:
        output = b"generated"
        adapter = _RecordingKindAdapter(output)
        probe_calls: list[Path] = []

        def probe(path: Path, media_type: str, contract: object) -> dict[str, object]:
            probe_calls.append(path)
            return _probe(path, media_type, contract)

        adapters = {
            "ai_generated": adapter.binding("ai_generated", "ai"),
            "artifact_probe": executor.ArtifactProbe(
                probe_id="counting-probe", probe_version="1", probe=probe
            ),
        }
        request = _request(_ai_component(output))
        first = executor.execute_component(self.job, request, adapters=adapters)
        second = executor.execute_component(self.job, request, adapters=adapters)

        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(len(probe_calls), 1)

    def test_export_published_binding_is_read_only_and_checks_output(self) -> None:
        output = b"generated"
        adapter = _RecordingKindAdapter(output)
        adapters = _kind_registry({"ai_generated": adapter})
        request = _request(_ai_component(output))
        first = executor.execute_component(self.job, request, adapters=adapters)
        def snapshot():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.job.job_dir.rglob('*') if p.is_file()}
        before = snapshot()
        result = executor.export_published_execution_binding(self.job, request, adapters=adapters)
        self.assertEqual(result['state'], 'published')
        self.assertEqual(result['artifact_sha256'], _sha256(_canonical(dict(first))))
        self.assertEqual(result['output_sha256'], first.output_sha256)
        self.assertEqual(snapshot(), before)
        self.assertEqual(len(adapter.calls), 1)
        (self.job.job_dir / first.job_path).write_bytes(b'changed')
        with self.assertRaises(executor.BrollComponentExecutionError):
            executor.export_published_execution_binding(self.job, request, adapters=adapters)

    def test_published_conflicting_input_is_rejected_before_adapter_and_preserves_final(self) -> None:
        first_output = b"first"
        first = _RecordingKindAdapter(first_output)
        component = _ai_component(first_output)
        artifact = executor.execute_component(
            self.job,
            _request(component),
            adapters={
                "ai_generated": first.binding("ai_generated", "ai"),
                "artifact_probe": _artifact_probe(),
            },
        )
        final = self.job.job_dir / artifact.job_path
        receipt = final.with_name('.ai-r7.transaction.json')
        baseline = json.loads(receipt.read_text())
        changed = copy.deepcopy(component)
        changed["generation_id"] = "generation-002"
        for state in ('published', 'publishing', 'complete'):
            with self.subTest(state=state):
                record = copy.deepcopy(baseline)
                record['state'] = state
                if state == 'complete':
                    record['output_identity'] = None
                raw = _canonical(record) + b'\n'
                receipt.write_bytes(raw)
                second = _RecordingKindAdapter(b"second")
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    executor.execute_component(
                        self.job,
                        _request(changed),
                        adapters={
                            "ai_generated": second.binding("ai_generated", "ai"),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
                self.assertEqual(second.calls, [])
                self.assertEqual(receipt.read_bytes(), raw)
                self.assertEqual(final.read_bytes(), first_output)

    def test_stale_unfinished_transaction_rebuild_requires_absent_final(self) -> None:
        for state in ('planned', 'running'):
            for existing_output in (False, True):
                with self.subTest(state=state, existing_output=existing_output):
                    output = b'approved-output'
                    component_id = f'stale-{state}-{existing_output}'
                    component = _ai_component(output, component_id=component_id)
                    artifact = executor.execute_component(self.job, _request(component),
                        adapters=_kind_registry({'ai_generated': _RecordingKindAdapter(output)}))
                    final = self.job.job_dir / artifact.job_path
                    receipt = final.with_name(f'.{component_id}-r7.transaction.json')
                    record = json.loads(receipt.read_text())
                    record.update(state=state, output_sha256=None, byte_count=None,
                                  output_identity=None, artifact=None)
                    if state == 'planned':
                        record['nonce_identity'] = None
                    raw = _canonical(record) + b'\n'
                    receipt.write_bytes(raw)
                    if not existing_output:
                        final.unlink()
                    changed = copy.deepcopy(component)
                    changed['generation_id'] = 'generation-002'
                    adapter = _RecordingKindAdapter(output)
                    adapters = _kind_registry({'ai_generated': adapter})
                    if existing_output:
                        with self.assertRaises(executor.BrollComponentExecutionError):
                            executor.execute_component(self.job, _request(changed), adapters=adapters)
                        self.assertEqual(adapter.calls, [])
                        self.assertEqual(receipt.read_bytes(), raw)
                    else:
                        rebuilt = executor.execute_component(self.job, _request(changed), adapters=adapters)
                        self.assertEqual(len(adapter.calls), 1)
                        self.assertNotEqual(rebuilt.input_sha256, artifact.input_sha256)
                        self.assertEqual(json.loads(receipt.read_text())['state'], 'published')
                    self.assertEqual(final.read_bytes(), output)

    def test_published_receipt_is_canonical_durable_and_cross_bound(self) -> None:
        output = b"generated"
        request = _request(_ai_component(output))
        artifact = executor.execute_component(
            self.job,
            request,
            adapters={
                "ai_generated": _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                ),
                "artifact_probe": _artifact_probe(),
            },
        )
        receipt = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/.ai-r7.transaction.json"
        )
        raw = receipt.read_bytes()
        record = json.loads(raw)
        self.assertEqual(raw, _canonical(record) + b"\n")
        self.assertEqual(record["state"], "published")
        self.assertEqual(record["input_sha256"], artifact.input_sha256)
        self.assertEqual(record["component_id"], artifact.component_id)
        self.assertEqual(record["output_sha256"], artifact.output_sha256)
        self.assertEqual(record["output_job_path"], artifact.job_path)
        self.assertEqual(record["artifact"]["media_probe"], dict(artifact.media_probe))

    def test_canonical_receipt_with_mutated_artifact_is_rejected_before_replay(self) -> None:
        output = b"generated"
        request = _request(_ai_component(output))
        artifact = executor.execute_component(
            self.job,
            request,
            adapters={
                "ai_generated": _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                ),
                "artifact_probe": _artifact_probe(),
            },
        )
        receipt = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/.ai-r7.transaction.json"
        )
        record = json.loads(receipt.read_text())
        record["artifact"]["z_index"] = 99
        receipt.write_bytes(_canonical(record) + b"\n")
        adapter = _RecordingKindAdapter(output)
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "ai_generated": adapter.binding("ai_generated", "ai"),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(adapter.calls, [])
        self.assertEqual((self.job.job_dir / artifact.job_path).read_bytes(), output)

    def test_unrelated_staging_sibling_and_permissions_are_preserved(self) -> None:
        stage_root = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/.staging"
        )
        unrelated = stage_root / "unrelated"
        unrelated.mkdir(parents=True)
        unrelated_file = unrelated / "keep.txt"
        unrelated_file.write_text("keep")
        stage_root.chmod(0o750)
        before_mode = stat.S_IMODE(stage_root.stat().st_mode)

        executor.execute_component(
            self.job,
            _request(_ai_component(b"generated")),
            adapters={
                "ai_generated": _RecordingKindAdapter(b"generated").binding(
                    "ai_generated", "ai"
                ),
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertEqual(unrelated_file.read_text(), "keep")
        self.assertEqual(stat.S_IMODE(stage_root.stat().st_mode), before_mode)

    def test_real_process_crashes_recover_publish_without_reinvoking_adapter(self) -> None:
        points = (
            "after_complete_receipt",
            "after_publish_link",
            "after_publish_unlink",
            "after_published_receipt",
        )
        for index, point in enumerate(points):
            with self.subTest(point=point):
                output = f"crash-output-{index}".encode()
                component = _ai_component(output, component_id=f"crash-{index}")
                request = _request(component)
                child = "\n".join(
                    (
                        "import os",
                        "from pathlib import Path",
                        "from edit.hd.tools import broll_component_executor as e",
                        "class Job:",
                        f"    job_id = {self.job.job_id!r}",
                        f"    job_dir = Path({str(self.job.job_dir)!r})",
                        "def invoke(context):",
                        f"    context.staging_path.write_bytes({output!r})",
                        "    return e.AdapterResult(invocation_evidence={'child': True}, qa={'passed': True, 'checks': ['generated']})",
                        "def probe(path, media_type, contract):",
                        "    return {'media_type': media_type, 'container': 'mp4', 'codec': 'h264', 'pixel_format': 'yuv420p', 'alpha': contract['alpha'], 'width': contract['width'], 'height': contract['height'], 'fps': contract['fps'], 'frame_count': 48, 'duration': 2.0}",
                        "def checkpoint(name):",
                        f"    if name == {point!r}: os._exit(73)",
                        "e._crash_checkpoint = checkpoint",
                        "e.execute_component(Job(), e.ComponentExecutionRequest("
                        f"recipe={request.recipe!r}, component_id={request.component_id!r}), adapters={{",
                        "    'ai_generated': e.KindAdapter(kind='ai_generated', approved_executor='approved:ai_generated', adapter_id='ai', adapter_version='1.0.0', artifact_media_type='video', invoke=invoke, provider='xAI', model='grok-imagine-video', endpoint_id='video-generation'),",
                        "    'artifact_probe': e.ArtifactProbe(probe_id='approved-media-probe', probe_version='1.0.0', probe=probe),",
                        "})",
                    )
                )
                result = subprocess.run(
                    [sys.executable, "-c", child],
                    cwd=Path(__file__).resolve().parents[3],
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(
                    result.returncode, 73, (result.stdout, result.stderr)
                )
                must_not_run = _RecordingKindAdapter(
                    output, failure=AssertionError("recovery must not invoke")
                )
                artifact = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": must_not_run.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(must_not_run.calls, [])
                self.assertEqual(
                    (self.job.job_dir / artifact.job_path).read_bytes(), output
                )
                parent = artifact.job_path.rsplit("/", 1)[0]
                stage_root = self.job.job_dir / parent / ".staging"
                if stage_root.exists():
                    self.assertFalse(
                        any(
                            child.name.startswith(f"journal-first-{index}-r7.")
                            for child in stage_root.iterdir()
                        )
                    )
                self.assertFalse(
                    any(
                        child.name.endswith(".next")
                        for child in (self.job.job_dir / parent).iterdir()
                    )
                )

    def test_published_receipt_rejects_probe_and_evidence_record_changes(self) -> None:
        output = b"exact-replay"
        request = _request(_ai_component(output, component_id="exact"))
        first = _RecordingKindAdapter(output)
        artifact = executor.execute_component(
            self.job,
            request,
            adapters={
                "ai_generated": first.binding("ai_generated", "ai"),
                "artifact_probe": _artifact_probe(),
            },
        )
        receipt = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/.exact-r7.transaction.json"
        )
        baseline = json.loads(receipt.read_text())

        mutations = {
            "artifact schema bool": lambda record: record["artifact"].__setitem__(
                "schema_version", True
            ),
            "z index bool": lambda record: record["artifact"].__setitem__(
                "z_index", False
            ),
            "opacity bool": lambda record: record["artifact"].__setitem__(
                "opacity", True
            ),
            "nested z bool": lambda record: record["artifact"][
                "render_window"
            ].__setitem__("z_index", False),
            "contract width bool": lambda record: record["artifact"][
                "artifact_contract"
            ].__setitem__("width", True),
            "safe zone bool": lambda record: record["artifact"][
                "safe_zone"
            ].__setitem__("top", True),
            "bad container": lambda record: record["artifact"][
                "media_probe"
            ].__setitem__("container", "avi"),
            "frame count bool": lambda record: record["artifact"][
                "media_probe"
            ].__setitem__("frame_count", True),
            "bad duration": lambda record: record["artifact"][
                "media_probe"
            ].__setitem__("duration", 99.0),
            "forged evidence": lambda record: record["artifact"][
                "invocation_evidence"
            ].__setitem__("approved_executor", "unapproved"),
            "input hash": lambda record: record.__setitem__(
                "input_sha256", "0" * 64
            ),
            "output hash": lambda record: record.__setitem__(
                "output_sha256", "1" * 64
            ),
            "adapter version": lambda record: record["adapter_binding"].__setitem__(
                "adapter_version", "2.0.0"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = copy.deepcopy(baseline)
                mutate(record)
                raw = _canonical(record) + b"\n"
                receipt.write_bytes(raw)
                adapter = _RecordingKindAdapter(
                    output, failure=AssertionError("must not invoke")
                )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": adapter.binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(adapter.calls, [])
                self.assertEqual(receipt.read_bytes(), raw)
                self.assertEqual(
                    (self.job.job_dir / artifact.job_path).read_bytes(), output
                )
        receipt.write_bytes(_canonical(baseline) + b"\n")

    def test_published_final_requires_regular_nonblocking_file(self) -> None:
        for index, mutation in enumerate(("fifo", "directory", "mode")):
            with self.subTest(mutation=mutation):
                component_id = f"published-final-{index}"
                output = f"published-output-{index}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                artifact = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": _RecordingKindAdapter(output).binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                final = self.job.job_dir / artifact.job_path
                if mutation == "fifo":
                    final.unlink()
                    os.mkfifo(final)
                elif mutation == "directory":
                    final.unlink()
                    final.mkdir()
                else:
                    final.chmod(0o644)
                marker = self.root / f"published-callback-{index}"

                def invoke(
                    context: executor.AdapterContext,
                ) -> executor.AdapterResult:
                    marker.write_text("called")
                    context.staging_path.write_bytes(output)
                    return executor.AdapterResult(
                        invocation_evidence={"unexpected": True},
                        qa={"passed": True, "checks": ["unexpected"]},
                    )

                base = _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                )
                adapter = executor.KindAdapter(
                    **{**base.__dict__, "invoke": invoke}
                )
                pid = os.fork()
                if pid == 0:
                    try:
                        executor.execute_component(
                            self.job,
                            request,
                            adapters={
                                "ai_generated": adapter,
                                "artifact_probe": _artifact_probe(),
                            },
                        )
                    except executor.BrollComponentExecutionError as failure:
                        os._exit(
                            73
                            if failure.error_code
                            == "BROLL_GENERATION_FAILED"
                            else 74
                        )
                    os._exit(0)
                deadline = time.monotonic() + 1.0
                status = None
                while time.monotonic() < deadline:
                    waited, current = os.waitpid(pid, os.WNOHANG)
                    if waited == pid:
                        status = current
                        break
                    time.sleep(0.01)
                if status is None:
                    os.kill(pid, signal.SIGKILL)
                    _waited, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                self.assertFalse(marker.exists())
                self.assertTrue(final.exists())
                if mutation == "mode":
                    self.assertEqual(stat.S_IMODE(final.stat().st_mode), 0o644)

    def test_normal_return_rechecks_complete_chain_after_durable_publish(self) -> None:
        for target in ("job", "visual"):
            with self.subTest(target=target):
                component_id = f"normal-chain-{target}"
                output = f"normal-{target}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                replacement: tuple[Path, Path, Path] | None = None

                def checkpoint(name: str) -> None:
                    nonlocal replacement
                    if name == "after_published_receipt" and replacement is None:
                        replacement = self._replace_output_chain(
                            target, component_id
                        )

                failure: executor.BrollComponentExecutionError | None = None
                try:
                    with mock.patch.object(
                        executor, "_crash_checkpoint", side_effect=checkpoint
                    ):
                        try:
                            executor.execute_component(
                                self.job,
                                request,
                                adapters={
                                    "ai_generated": _RecordingKindAdapter(
                                        output
                                    ).binding("ai_generated", "ai"),
                                    "artifact_probe": _artifact_probe(),
                                },
                            )
                        except executor.BrollComponentExecutionError as caught:
                            failure = caught
                    self.assertIsNotNone(replacement)
                    assert replacement is not None
                    final, journal = self._moved_artifact_paths(
                        replacement[1], target, component_id
                    )
                    self.assertEqual(final.read_bytes(), output)
                    self.assertTrue(journal.is_file())
                finally:
                    if replacement is not None:
                        self._restore_output_chain(*replacement)
                self.assertIsNotNone(failure)
                assert failure is not None
                self.assertEqual(
                    failure.error_code, "BROLL_GENERATION_FAILED"
                )
                no_retry = _RecordingKindAdapter(
                    output, failure=AssertionError("must replay")
                )
                replay = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": no_retry.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(no_retry.calls, [])
                self.assertEqual(
                    (self.job.job_dir / replay.job_path).read_bytes(), output
                )

    def test_try_replay_rechecks_complete_chain_before_return(self) -> None:
        original_cleanup = executor._cleanup_recorded_nonce
        for target in ("job", "visual"):
            with self.subTest(target=target):
                component_id = f"try-replay-chain-{target}"
                output = f"try-replay-{target}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": _RecordingKindAdapter(output).binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                replacement: tuple[Path, Path, Path] | None = None

                def cleanup(
                    transaction: object, code: str
                ) -> None:
                    nonlocal replacement
                    original_cleanup(transaction, code)
                    if replacement is None:
                        replacement = self._replace_output_chain(
                            target, component_id
                        )

                no_retry = _RecordingKindAdapter(
                    output, failure=AssertionError("must replay")
                )
                failure: executor.BrollComponentExecutionError | None = None
                try:
                    with mock.patch.object(
                        executor,
                        "_cleanup_recorded_nonce",
                        side_effect=cleanup,
                    ):
                        try:
                            executor.execute_component(
                                self.job,
                                request,
                                adapters={
                                    "ai_generated": no_retry.binding(
                                        "ai_generated", "ai"
                                    ),
                                    "artifact_probe": _artifact_probe(),
                                },
                            )
                        except executor.BrollComponentExecutionError as caught:
                            failure = caught
                    self.assertIsNotNone(replacement)
                    assert replacement is not None
                    final, journal = self._moved_artifact_paths(
                        replacement[1], target, component_id
                    )
                    self.assertEqual(final.read_bytes(), output)
                    self.assertTrue(journal.is_file())
                finally:
                    if replacement is not None:
                        self._restore_output_chain(*replacement)
                self.assertIsNotNone(failure)
                assert failure is not None
                self.assertEqual(
                    failure.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(no_retry.calls, [])
                replay = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": no_retry.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(no_retry.calls, [])
                self.assertEqual(
                    (self.job.job_dir / replay.job_path).read_bytes(), output
                )

    def test_begin_recovery_rechecks_complete_chain_after_durable_publish(self) -> None:
        for target in ("job", "visual"):
            with self.subTest(target=target):
                component_id = f"begin-recover-chain-{target}"
                output = f"begin-recover-{target}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                pid = os.fork()
                if pid == 0:
                    executor._crash_checkpoint = lambda name: (
                        os._exit(73)
                        if name == "after_complete_receipt"
                        else None
                    )
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": _RecordingKindAdapter(
                                output
                            ).binding("ai_generated", "ai"),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                    os._exit(0)
                _waited, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                replacement: tuple[Path, Path, Path] | None = None

                def checkpoint(name: str) -> None:
                    nonlocal replacement
                    if name == "after_published_receipt" and replacement is None:
                        replacement = self._replace_output_chain(
                            target, component_id
                        )

                no_retry = _RecordingKindAdapter(
                    output, failure=AssertionError("must recover")
                )
                failure: executor.BrollComponentExecutionError | None = None
                try:
                    with mock.patch.object(
                        executor,
                        "_try_replay_transaction",
                        return_value=None,
                    ), mock.patch.object(
                        executor, "_crash_checkpoint", side_effect=checkpoint
                    ):
                        try:
                            executor.execute_component(
                                self.job,
                                request,
                                adapters={
                                    "ai_generated": no_retry.binding(
                                        "ai_generated", "ai"
                                    ),
                                    "artifact_probe": _artifact_probe(),
                                },
                            )
                        except executor.BrollComponentExecutionError as caught:
                            failure = caught
                    self.assertIsNotNone(replacement)
                    assert replacement is not None
                    final, journal = self._moved_artifact_paths(
                        replacement[1], target, component_id
                    )
                    self.assertEqual(final.read_bytes(), output)
                    self.assertTrue(journal.is_file())
                finally:
                    if replacement is not None:
                        self._restore_output_chain(*replacement)
                self.assertIsNotNone(failure)
                assert failure is not None
                self.assertEqual(
                    failure.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(no_retry.calls, [])
                replay = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": no_retry.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(no_retry.calls, [])
                self.assertEqual(
                    (self.job.job_dir / replay.job_path).read_bytes(), output
                )

    def test_executor_evidence_contains_complete_approved_kind_binding(self) -> None:
        output = b"bound-evidence"
        artifact = executor.execute_component(
            self.job,
            _request(_ai_component(output, component_id="bound")),
            adapters={
                "ai_generated": _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                ),
                "artifact_probe": _artifact_probe(),
            },
        )
        evidence = artifact.invocation_evidence
        self.assertEqual(evidence["kind"], "ai_generated")
        self.assertEqual(evidence["approved_executor"], "approved:ai_generated")
        self.assertEqual(evidence["provider"], "xAI")
        self.assertEqual(evidence["model"], "grok-imagine-video")
        self.assertEqual(evidence["endpoint_id"], "video-generation")

    def test_adapter_retained_staging_fd_cannot_change_published_inode(self) -> None:
        output = b"immutable-published-bytes"
        retained: list[int] = []

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            descriptor = os.open(context.staging_path, os.O_RDWR)
            retained.append(descriptor)
            os.write(descriptor, output)
            os.fsync(descriptor)
            return executor.AdapterResult(
                invocation_evidence={"adapter": "retained-fd"},
                qa={"passed": True, "checks": ["generated"]},
            )

        adapter = executor.KindAdapter(
            kind="ai_generated",
            approved_executor="approved:ai_generated",
            adapter_id="retained-fd",
            adapter_version="1",
            artifact_media_type="video",
            invoke=invoke,
            provider="xAI",
            model="grok-imagine-video",
            endpoint_id="video-generation",
        )
        artifact = executor.execute_component(
            self.job,
            _request(_ai_component(output, component_id="retained")),
            adapters={"ai_generated": adapter, "artifact_probe": _artifact_probe()},
        )
        final = self.job.job_dir / artifact.job_path
        try:
            os.lseek(retained[0], 0, os.SEEK_SET)
            os.write(retained[0], b"changed-after-publish")
            os.ftruncate(retained[0], len(b"changed-after-publish"))
            os.fsync(retained[0])
        finally:
            os.close(retained[0])
        self.assertEqual(final.read_bytes(), output)
        self.assertEqual(_sha256(final.read_bytes()), artifact.output_sha256)

    def test_probe_retained_staging_fd_cannot_change_published_inode(self) -> None:
        output = b"probe-retained-output"
        retained: list[int] = []

        def probe(path: Path, media_type: str, contract: object) -> dict[str, object]:
            retained.append(os.open(path, os.O_RDWR))
            return _probe(path, media_type, contract)

        artifact = executor.execute_component(
            self.job,
            _request(_ai_component(output, component_id="probe-retained")),
            adapters={
                "ai_generated": _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                ),
                "artifact_probe": executor.ArtifactProbe(
                    probe_id="approved-media-probe",
                    probe_version="1.0.0",
                    probe=probe,
                ),
            },
        )
        final = self.job.job_dir / artifact.job_path
        try:
            os.lseek(retained[0], 0, os.SEEK_SET)
            os.write(retained[0], b"changed-by-retained-probe")
            os.ftruncate(retained[0], len(b"changed-by-retained-probe"))
            os.fsync(retained[0])
        finally:
            os.close(retained[0])
        self.assertEqual(final.read_bytes(), output)

    def test_missing_material_source_creates_no_task7_state(self) -> None:
        component = _material_component(
            "local_material",
            relative="materials/missing.mp4",
            source_sha="a" * 64,
            component_id="missing-source",
        )
        adapter = _RecordingKindAdapter(b"unused")
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "local_material": adapter.binding(
                        "local_material", "local"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_COMPOSITE_FAILED")
        self.assertEqual(adapter.calls, [])
        self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_short_os_writes_are_completed_for_journal_and_snapshots(self) -> None:
        output = b"short-write-output"
        original_write = os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[: max(1, len(payload) // 3)])

        with mock.patch.object(executor.os, "write", side_effect=short_write):
            artifact = executor.execute_component(
                self.job,
                _request(_ai_component(output, component_id="short-write")),
                adapters={
                    "ai_generated": _RecordingKindAdapter(output).binding(
                        "ai_generated", "ai"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(
            (self.job.job_dir / artifact.job_path).read_bytes(), output
        )
        receipt = (
            self.job.job_dir
            / "08-visual-assets/components/seg-001/.short-write-r7.transaction.json"
        )
        self.assertEqual(receipt.read_bytes(), _canonical(json.loads(receipt.read_text())) + b"\n")

    def test_short_os_writes_preserve_material_source_snapshot(self) -> None:
        source = b"material-source-short-write"
        output = b"normalized-short-write"
        component = _material_component(
            "local_material",
            relative="materials/source.mp4",
            source_sha=_sha256(source),
            component_id="source-short-write",
        )
        _write_job_file(self.job, str(component["job_path"]), source)
        seen: list[bytes] = []

        def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
            self.assertIsNotNone(context.source_path)
            seen.append(context.source_path.read_bytes())
            context.staging_path.write_bytes(output)
            return executor.AdapterResult(
                invocation_evidence={"completed": True},
                qa={"passed": True, "checks": ["normalized"]},
            )

        original_write = os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[: max(1, len(payload) // 4)])

        with mock.patch.object(executor.os, "write", side_effect=short_write):
            artifact = executor.execute_component(
                self.job,
                _request(component),
                adapters={
                    "local_material": executor.KindAdapter(
                        kind="local_material",
                        approved_executor="approved:local_material",
                        adapter_id="local",
                        adapter_version="1.0.0",
                        artifact_media_type="video",
                        invoke=invoke,
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )

        self.assertEqual(seen, [source])
        self.assertEqual((self.job.job_dir / artifact.job_path).read_bytes(), output)

    def test_journal_first_crash_points_recover_without_nonce_or_next_record_orphans(self) -> None:
        points = (
            "after_planned_receipt",
            "after_nonce_mkdir",
            "after_running_receipt",
        )
        for index, point in enumerate(points):
            with self.subTest(point=point):
                output = f"journal-first-{index}".encode()
                request = _request(
                    _ai_component(output, component_id=f"journal-first-{index}")
                )
                pid = os.fork()
                if pid == 0:
                    def checkpoint(name: str) -> None:
                        if name == point:
                            os._exit(73)

                    executor._crash_checkpoint = checkpoint
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": _RecordingKindAdapter(output).binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                    os._exit(0)
                waited, status = os.waitpid(pid, 0)
                self.assertEqual(waited, pid)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                recovered_adapter = _RecordingKindAdapter(output)
                artifact = executor.execute_component(
                    self.job,
                    request,
                    adapters={
                        "ai_generated": recovered_adapter.binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(len(recovered_adapter.calls), 1)
                self.assertEqual(
                    (self.job.job_dir / artifact.job_path).read_bytes(), output
                )

    def test_input_snapshot_crash_recovers_owned_nonempty_nonce(self) -> None:
        source = b"approved-local-source"
        output = b"recovered-local-output"
        component_id = "input-snapshot-crash"
        component = _material_component(
            "local_material",
            relative="inputs/crash-source.mp4",
            source_sha=_sha256(source),
            component_id=component_id,
        )
        _write_job_file(self.job, str(component["job_path"]), source)
        request = _request(component)
        pid = os.fork()
        if pid == 0:
            executor._crash_checkpoint = lambda name: (
                os._exit(73)
                if name == "after_input_snapshot_before_running"
                else None
            )
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "local_material": _RecordingKindAdapter(output).binding(
                        "local_material", "local"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
            os._exit(0)
        _waited, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 73)
        parent = self.job.job_dir / "08-visual-assets/components/seg-001"
        journal = parent / f".{component_id}-r7.transaction.json"
        record = json.loads(journal.read_text())
        self.assertEqual(record["state"], "running")
        self.assertEqual(len(record["nonce_identity"]), 2)
        nonce = parent / ".staging" / record["nonce"]
        self.assertEqual(
            [child.name for child in nonce.iterdir()], ["input.snapshot"]
        )

        recovered = _RecordingKindAdapter(output)
        artifact = executor.execute_component(
            self.job,
            request,
            adapters={
                "local_material": recovered.binding(
                    "local_material", "local"
                ),
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertEqual(len(recovered.calls), 1)
        self.assertEqual(
            (self.job.job_dir / artifact.job_path).read_bytes(), output
        )
        stage_root = parent / ".staging"
        self.assertFalse(
            any(
                child.name.startswith(f"{component_id}-r7.")
                for child in stage_root.iterdir()
            )
        )

    def test_staged_validation_failures_do_not_accumulate_file_descriptors(self) -> None:
        scenarios: list[tuple[str, object, dict[str, object]]] = []

        stock_source = b"stock-source"
        stock = _material_component(
            "external_stock",
            relative="ignored.mp4",
            source_sha=_sha256(stock_source),
            component_id="fd-stock",
        )
        stock_path = _write_job_file(
            self.job, str(stock["job_path"]), stock_source
        )
        _write_stock_license(self.job, stock, stock_source)
        stock_path.unlink()
        scenarios.append(
            (
                "stock source missing",
                _request(stock),
                {
                    "external_stock": _RecordingKindAdapter(
                        b"unused"
                    ).binding("external_stock", "stock"),
                    "artifact_probe": _artifact_probe(),
                },
            )
        )

        parent = self.job.job_dir / "08-visual-assets/components/seg-001"
        parent.mkdir(parents=True, exist_ok=True)
        journal_component = "fd-journal"
        os.mkfifo(parent / f".{journal_component}-r7.transaction.json")
        scenarios.append(
            (
                "journal special type",
                _request(
                    _ai_component(b"unused", component_id=journal_component)
                ),
                {
                    "ai_generated": _RecordingKindAdapter(b"unused").binding(
                        "ai_generated", "ai"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        )

        lock_component = "fd-lock"
        os.mkfifo(parent / f".{lock_component}-r7.lock")
        scenarios.append(
            (
                "lock special type",
                _request(_ai_component(b"unused", component_id=lock_component)),
                {
                    "ai_generated": _RecordingKindAdapter(b"unused").binding(
                        "ai_generated", "ai"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        )

        for name, request, adapters in scenarios:
            with self.subTest(name=name):
                before = len(os.listdir("/dev/fd"))
                for _ in range(20):
                    with self.assertRaises(
                        executor.BrollComponentExecutionError
                    ):
                        executor.execute_component(
                            self.job, request, adapters=adapters
                        )
                after = len(os.listdir("/dev/fd"))
                self.assertEqual(after - before, 0)

    def test_probe_closing_its_fd_returns_stable_kind_error(self) -> None:
        def closing_probe(
            path: Path, media_type: str, contract: object
        ) -> dict[str, object]:
            os.close(int(path.name))
            return {
                "media_type": media_type,
                "container": "mp4",
                "codec": "h264",
                "pixel_format": "yuv420p",
                "alpha": contract["alpha"],
                "width": contract["width"],
                "height": contract["height"],
                "fps": contract["fps"],
                "frame_count": 48,
                "duration": 2.0,
            }

        cases = (
            (
                "ai_generated",
                _request(_ai_component(b"probe-output", component_id="probe-ai")),
                _RecordingKindAdapter(b"probe-output").binding(
                    "ai_generated", "ai"
                ),
                "BROLL_GENERATION_FAILED",
            ),
            (
                "local_material",
                _request(
                    _material_component(
                        "local_material",
                        relative="inputs/probe-local.mp4",
                        source_sha=_sha256(b"probe-source"),
                        component_id="probe-local",
                    )
                ),
                _RecordingKindAdapter(b"probe-output").binding(
                    "local_material", "local"
                ),
                "BROLL_COMPOSITE_FAILED",
            ),
        )
        _write_job_file(
            self.job, "inputs/probe-local.mp4", b"probe-source"
        )
        probe = executor.ArtifactProbe(
            probe_id="closing-probe",
            probe_version="1.0.0",
            probe=closing_probe,
        )
        for kind, request, adapter, error_code in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={kind: adapter, "artifact_probe": probe},
                    )
                self.assertEqual(caught.exception.error_code, error_code)
                self.assertEqual(
                    caught.exception.allowed_actions,
                    ("retry_same_strategy", "replan_visual_direction"),
                )

    def test_planned_receipt_preserves_nonempty_replaced_or_moded_nonce(self) -> None:
        cases = (
            ("after_planned_receipt", "nonempty"),
            ("after_nonce_mkdir", "replacement"),
            ("after_planned_receipt", "mode"),
        )
        for index, (point, mutation) in enumerate(cases):
            with self.subTest(point=point, mutation=mutation):
                component_id = f"planned-unrelated-{index}"
                output = f"planned-output-{index}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                pid = os.fork()
                if pid == 0:
                    def checkpoint(name: str) -> None:
                        if name == point:
                            os._exit(73)

                    executor._crash_checkpoint = checkpoint
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": _RecordingKindAdapter(
                                output
                            ).binding("ai_generated", "ai"),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                    os._exit(0)
                _waited, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                receipt = self.job.job_dir / (
                    "08-visual-assets/components/seg-001/"
                    f".{component_id}-r7.transaction.json"
                )
                record = json.loads(receipt.read_text())
                stage_root = receipt.parent / ".staging"
                stage_root.mkdir(mode=0o700, exist_ok=True)
                nonce = stage_root / record["nonce"]
                moved = nonce.with_name(f"{nonce.name}.owned")
                if mutation == "replacement":
                    nonce.rename(moved)
                    nonce.mkdir(mode=0o700)
                    (nonce / "unrelated.txt").write_text("keep")
                elif mutation == "nonempty":
                    nonce.mkdir(mode=0o700)
                    (nonce / "unrelated.txt").write_text("keep")
                else:
                    nonce.mkdir(mode=0o755)
                blocked = _RecordingKindAdapter(
                    output, failure=AssertionError("must not invoke")
                )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": blocked.binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(blocked.calls, [])
                self.assertTrue(nonce.exists())
                if mutation != "mode":
                    self.assertEqual(
                        (nonce / "unrelated.txt").read_text(), "keep"
                    )
                if mutation == "replacement":
                    self.assertTrue(moved.exists())

    def test_planned_and_running_receipts_reject_adapter_or_probe_rebinding(self) -> None:
        cases = (
            ("after_planned_receipt", "adapter"),
            ("after_running_receipt", "probe"),
        )
        for index, (point, change) in enumerate(cases):
            with self.subTest(point=point, change=change):
                output = f"binding-{index}".encode()
                request = _request(
                    _ai_component(output, component_id=f"binding-{index}")
                )
                pid = os.fork()
                if pid == 0:
                    def checkpoint(name: str) -> None:
                        if name == point:
                            os._exit(73)

                    executor._crash_checkpoint = checkpoint
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": _RecordingKindAdapter(output).binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                    os._exit(0)
                _waited, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                blocked = _RecordingKindAdapter(
                    output, failure=AssertionError("must not invoke")
                )
                binding = blocked.binding("ai_generated", "ai")
                probe = _artifact_probe()
                if change == "adapter":
                    binding = executor.KindAdapter(
                        **{**binding.__dict__, "adapter_version": "2"}
                    )
                else:
                    probe = executor.ArtifactProbe(
                        probe_id=probe.probe_id,
                        probe_version="2",
                        probe=lambda *_args: (_ for _ in ()).throw(
                            AssertionError("must not probe")
                        ),
                    )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": binding,
                            "artifact_probe": probe,
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(blocked.calls, [])

    def test_complete_and_publishing_receipts_reject_cross_binding_changes(self) -> None:
        cases = (
            ("after_complete_receipt", "probe"),
            ("after_publish_link", "output"),
        )
        for index, (point, mutation) in enumerate(cases):
            with self.subTest(point=point, mutation=mutation):
                output = f"late-state-{index}".encode()
                component_id = f"late-state-{index}"
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                pid = os.fork()
                if pid == 0:
                    def checkpoint(name: str) -> None:
                        if name == point:
                            os._exit(73)

                    executor._crash_checkpoint = checkpoint
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": _RecordingKindAdapter(output).binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                    os._exit(0)
                _waited, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 73)
                journal = (
                    self.job.job_dir
                    / "08-visual-assets/components/seg-001"
                    / f".{component_id}-r7.transaction.json"
                )
                record = json.loads(journal.read_text())
                if mutation == "probe":
                    record["artifact"]["media_probe"]["container"] = "avi"
                else:
                    record["output_sha256"] = "0" * 64
                journal.write_bytes(_canonical(record) + b"\n")
                blocked = _RecordingKindAdapter(
                    output, failure=AssertionError("must not invoke")
                )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        request,
                        adapters={
                            "ai_generated": blocked.binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(blocked.calls, [])

    def test_preset_journal_fifo_and_directory_fail_immediately_without_callback(self) -> None:
        for kind in ("fifo", "directory"):
            with self.subTest(kind=kind):
                component_id = f"preset-{kind}"
                parent = (
                    self.job.job_dir
                    / "08-visual-assets/components/seg-001"
                )
                parent.mkdir(parents=True, exist_ok=True)
                journal = parent / f".{component_id}-r7.transaction.json"
                if kind == "fifo":
                    os.mkfifo(journal)
                else:
                    journal.mkdir()
                adapter = _RecordingKindAdapter(
                    b"unused", failure=AssertionError("must not invoke")
                )
                started = time.monotonic()
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        _request(
                            _ai_component(b"unused", component_id=component_id)
                        ),
                        adapters={
                            "ai_generated": adapter.binding(
                                "ai_generated", "ai"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertLess(time.monotonic() - started, 1.0)
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                self.assertEqual(adapter.calls, [])

    def test_preset_lock_and_stock_records_fail_immediately_without_callback(self) -> None:
        parent = self.job.job_dir / "08-visual-assets/components/seg-001"
        parent.mkdir(parents=True)
        lock = parent / ".preset-lock-r7.lock"
        os.mkfifo(lock)
        lock_adapter = _RecordingKindAdapter(
            b"unused", failure=AssertionError("must not invoke")
        )
        started = time.monotonic()
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_ai_component(b"unused", component_id="preset-lock")),
                adapters={
                    "ai_generated": lock_adapter.binding(
                        "ai_generated", "ai"
                    ),
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")
        self.assertEqual(lock_adapter.calls, [])

        for target in ("license", "receipt"):
            with self.subTest(target=target):
                payload = f"stock-{target}".encode()
                component = _material_component(
                    "external_stock",
                    relative="ignored.mp4",
                    source_sha=_sha256(payload),
                    component_id=f"stock-{target}",
                )
                _write_job_file(self.job, str(component["job_path"]), payload)
                license_path = _write_stock_license(self.job, component, payload)
                if target == "license":
                    license_path.unlink()
                    os.mkfifo(license_path)
                    blocked_path = license_path
                else:
                    key = "a" * 64
                    receipt = (
                        self.job.job_dir
                        / f"stock/{key[:2]}/{key}.download.json"
                    )
                    receipt.unlink()
                    os.mkfifo(receipt)
                    blocked_path = receipt
                adapter = _RecordingKindAdapter(
                    b"unused", failure=AssertionError("must not invoke")
                )
                started = time.monotonic()
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    executor.execute_component(
                        self.job,
                        _request(component),
                        adapters={
                            "external_stock": adapter.binding(
                                "external_stock", "stock"
                            ),
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertLess(time.monotonic() - started, 1.0)
                self.assertEqual(
                    caught.exception.error_code, "BROLL_DOWNLOAD_REJECTED"
                )
                self.assertEqual(adapter.calls, [])
                blocked_path.unlink()

    def test_job_root_and_visual_root_permanent_replacement_never_write_replacement(self) -> None:
        for target in ("job", "visual"):
            with self.subTest(target=target):
                output = f"replacement-{target}".encode()
                outside = self.root / f"outside-{target}"
                outside.mkdir()
                moved = self.root / f"moved-{target}"

                def invoke(context: executor.AdapterContext) -> executor.AdapterResult:
                    if target == "job":
                        self.job.job_dir.rename(moved)
                        self.job.job_dir.symlink_to(outside, target_is_directory=True)
                    else:
                        visual = self.job.job_dir / "08-visual-assets"
                        visual.rename(moved)
                        visual.symlink_to(outside, target_is_directory=True)
                    context.staging_path.write_bytes(output)
                    return executor.AdapterResult(
                        invocation_evidence={"completed": True},
                        qa={"passed": True, "checks": ["generated"]},
                    )

                base = _RecordingKindAdapter(output).binding(
                    "ai_generated", "ai"
                )
                try:
                    with self.assertRaises(
                        executor.BrollComponentExecutionError
                    ) as caught:
                        executor.execute_component(
                            self.job,
                            _request(
                                _ai_component(
                                    output, component_id=f"replace-{target}"
                                )
                            ),
                            adapters={
                                "ai_generated": executor.KindAdapter(
                                    **{**base.__dict__, "invoke": invoke}
                                ),
                                "artifact_probe": _artifact_probe(),
                            },
                        )
                    self.assertEqual(
                        caught.exception.error_code, "BROLL_GENERATION_FAILED"
                    )
                    self.assertEqual(list(outside.rglob("*")), [])
                finally:
                    if target == "job":
                        if self.job.job_dir.is_symlink():
                            self.job.job_dir.unlink()
                        if moved.exists():
                            moved.rename(self.job.job_dir)
                    else:
                        visual = self.job.job_dir / "08-visual-assets"
                        if visual.is_symlink():
                            visual.unlink()
                        if moved.exists():
                            moved.rename(visual)

    def test_publish_checkpoints_roll_back_through_pinned_parent_after_chain_replacement(self) -> None:
        for index, point in enumerate(
            ("after_publish_link", "after_publish_unlink")
        ):
            with self.subTest(point=point):
                component_id = f"publish-chain-{index}"
                output = f"publish-chain-output-{index}".encode()
                visual = self.job.job_dir / "08-visual-assets"
                moved = self.job.job_dir / f"08-moved-{index}"
                outside = self.root / f"publish-outside-{index}"
                outside.mkdir()

                def checkpoint(name: str) -> None:
                    if name == point:
                        visual.rename(moved)
                        visual.symlink_to(outside, target_is_directory=True)

                try:
                    with mock.patch.object(
                        executor, "_crash_checkpoint", side_effect=checkpoint
                    ):
                        with self.assertRaises(
                            executor.BrollComponentExecutionError
                        ) as caught:
                            executor.execute_component(
                                self.job,
                                _request(
                                    _ai_component(
                                        output, component_id=component_id
                                    )
                                ),
                                adapters={
                                    "ai_generated": _RecordingKindAdapter(
                                        output
                                    ).binding("ai_generated", "ai"),
                                    "artifact_probe": _artifact_probe(),
                                },
                            )
                    self.assertEqual(
                        caught.exception.error_code,
                        "BROLL_GENERATION_FAILED",
                    )
                    final = (
                        moved
                        / "components/seg-001"
                        / f"{component_id}-r7.mp4"
                    )
                    self.assertFalse(final.exists())
                    self.assertEqual(list(outside.iterdir()), [])
                finally:
                    if visual.is_symlink():
                        visual.unlink()
                    if moved.exists():
                        moved.rename(visual)
                retry = executor.execute_component(
                    self.job,
                    _request(
                        _ai_component(output, component_id=component_id)
                    ),
                    adapters={
                        "ai_generated": _RecordingKindAdapter(output).binding(
                            "ai_generated", "ai"
                        ),
                        "artifact_probe": _artifact_probe(),
                    },
                )
                self.assertEqual(
                    (self.job.job_dir / retry.job_path).read_bytes(), output
                )

    def test_link_result_replacement_is_preserved_for_new_and_recovered_publish(self) -> None:
        real_link = os.link
        replacement_bytes = b"replacement-final"
        for index, recovery in enumerate((False, True)):
            with self.subTest(recovery=recovery):
                component_id = f"link-replaced-{index}"
                output = f"owned-output-{index}".encode()
                request = _request(
                    _ai_component(output, component_id=component_id)
                )
                if recovery:
                    pid = os.fork()
                    if pid == 0:
                        def checkpoint(name: str) -> None:
                            if name == "after_complete_receipt":
                                os._exit(73)

                        executor._crash_checkpoint = checkpoint
                        executor.execute_component(
                            self.job,
                            request,
                            adapters={
                                "ai_generated": _RecordingKindAdapter(
                                    output
                                ).binding("ai_generated", "ai"),
                                "artifact_probe": _artifact_probe(),
                            },
                        )
                        os._exit(0)
                    _waited, status = os.waitpid(pid, 0)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 73)

                def replacing_link(
                    source: str,
                    destination: str,
                    *args: object,
                    **kwargs: object,
                ) -> None:
                    real_link(source, destination, *args, **kwargs)
                    parent_fd = kwargs["dst_dir_fd"]
                    os.unlink(destination, dir_fd=parent_fd)
                    descriptor = os.open(
                        destination,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    try:
                        os.write(descriptor, replacement_bytes)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)

                blocked = _RecordingKindAdapter(
                    output,
                    failure=(
                        AssertionError("recovery must not invoke")
                        if recovery
                        else None
                    ),
                )
                with mock.patch.object(
                    executor.os, "link", side_effect=replacing_link
                ):
                    with self.assertRaises(
                        executor.BrollComponentExecutionError
                    ) as caught:
                        executor.execute_component(
                            self.job,
                            request,
                            adapters={
                                "ai_generated": blocked.binding(
                                    "ai_generated", "ai"
                                ),
                                "artifact_probe": _artifact_probe(),
                            },
                        )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_GENERATION_FAILED"
                )
                if recovery:
                    self.assertEqual(blocked.calls, [])
                final = self.job.job_dir / (
                    "08-visual-assets/components/seg-001/"
                    f"{component_id}-r7.mp4"
                )
                self.assertEqual(final.read_bytes(), replacement_bytes)

    def test_image_probe_contract_controls_png_extension_and_rejects_bad_format(self) -> None:
        output = b"image-output"
        component = _ai_component(output, component_id="image")
        adapter = _RecordingKindAdapter(output).binding("ai_generated", "ai")
        adapter = executor.KindAdapter(
            **{**adapter.__dict__, "artifact_media_type": "image"}
        )
        artifact = executor.execute_component(
            self.job,
            _request(component),
            adapters={"ai_generated": adapter, "artifact_probe": _artifact_probe()},
        )
        self.assertTrue(artifact.job_path.endswith(".png"))
        self.assertIsNone(artifact.media_probe["fps"])
        self.assertEqual(artifact.media_probe["frame_count"], 1)
        replay_adapter = executor.KindAdapter(
            **{
                **adapter.__dict__,
                "invoke": lambda _context: (_ for _ in ()).throw(
                    AssertionError("image replay must not invoke")
                ),
            }
        )
        replay = executor.execute_component(
            self.job,
            _request(component),
            adapters={
                "ai_generated": replay_adapter,
                "artifact_probe": executor.ArtifactProbe(
                    probe_id="approved-media-probe",
                    probe_version="1.0.0",
                    probe=lambda *_args: (_ for _ in ()).throw(
                        AssertionError("image replay must not probe")
                    ),
                ),
            },
        )
        self.assertEqual(replay.output_sha256, artifact.output_sha256)

        bad_component = _ai_component(output, component_id="bad-image")

        def bad_probe(path: Path, media_type: str, contract: object) -> dict[str, object]:
            record = _probe(path, media_type, contract)
            record["container"] = "jpeg"
            return record

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(bad_component),
                adapters={
                    "ai_generated": adapter,
                    "artifact_probe": executor.ArtifactProbe(
                        probe_id="approved-media-probe",
                        probe_version="1.0.0",
                        probe=bad_probe,
                    ),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_GENERATION_FAILED")

    def _working_code_adapter(
        self,
        brief: bytes,
        output: bytes,
        *,
        dependency_id: str = "html-video",
        marker: Path | None = None,
        timeout_seconds: float = 2.0,
        request_only_values: tuple[str, ...] = (),
    ) -> executor.ReferenceProcessAdapter:
        root = self.root / f"dependency-{dependency_id}"
        root.mkdir(exist_ok=True)
        entrypoint = root / ("render.py" if dependency_id == "html-video" else "skill.py")
        marker_line = (
            f"Path({str(marker)!r}).write_text('called')"
            if marker is not None
            else "pass"
        )
        entrypoint.write_text(
            "from pathlib import Path\n"
            "import argparse, json, os, sys\n"
            "p=argparse.ArgumentParser()\n"
            "p.add_argument('--brief', required=True)\n"
            "p.add_argument('--output', required=True)\n"
            "a=p.parse_args()\n"
            f"{marker_line}\n"
            f"payload={output!r}\n"
            "Path(a.output).write_bytes(payload)\n",
            encoding="utf-8",
        )
        launcher = Path(sys.executable).resolve()
        return executor.ReferenceProcessAdapter(
            adapter_id="html-video-reference",
            dependency_id=dependency_id,
            approved_executor="approved:code_generated",
            dependency_root=root,
            entrypoint=entrypoint.name,
            entrypoint_sha256=_sha256(entrypoint.read_bytes()),
            producer_version="approved-version",
            primary_renderer="HyperFrames",
            renderer_version="approved-renderer",
            artifact_media_type="video",
            launcher=launcher,
            launcher_sha256=_sha256(launcher.read_bytes()),
            argv_template=(
                "{launcher}",
                "{entrypoint}",
                "--brief",
                "{brief_path}",
                "--output",
                "{output_path}",
            ),
            brief_loader=lambda _job, _recipe, _component: brief,
            timeout_seconds=timeout_seconds,
            request_only_values=request_only_values,
            self_contained_wrapper=True,
        )


class CodeDependencyExecutionTests(unittest.TestCase):
    def test_paper_freeze_failure_retains_bounded_native_diagnostic(self):
        from types import SimpleNamespace
        from edit.hd.tools import broll_component_executor as executor
        message = b'ValueError: paper output contains a continuous freeze >= 3 seconds: {"duration":3.08}\n'
        with self.assertRaises(executor.BrollComponentExecutionError) as raised:
            executor._raise_reference_failure(SimpleNamespace(dependency_id="paper-collage-ad"), message, {})
        self.assertEqual(str(raised.exception), "BROLL_RENDER_FAILED")
        self.assertIn("continuous freeze", raised.exception.__notes__[0])

    def test_prequalification_registry_is_forwarded_only_from_the_bound_adapter(self) -> None:
        from dataclasses import replace
        from unittest.mock import Mock, patch

        brief = b"{}"
        component = _code_component(brief, dependency_id="hyperframes")
        component["primary_renderer"] = "HyperFrames"
        qualification = {
            "path": "assets/verified-templates/hyperframes/candidate/qualification/source-registry.json",
            "sha256": "a" * 64,
        }
        adapter = replace(
            self._adapter(brief, "pass", dependency_id="hyperframes"),
            qualification_registry_path=qualification["path"],
            qualification_registry_sha256=qualification["sha256"],
        )
        policy = Mock()
        with patch("edit.hd.tools.visual_plan._load_router_module", return_value=policy):
            self.assertIs(executor._validate_code_adapter(adapter, component), adapter)
        policy.validate_template_binding.assert_called_once_with(
            component, qualification_registry=qualification
        )

    def test_hyperframes_reference_dependency_is_supported(self) -> None:
        brief = b"{}"
        component = _code_component(brief, dependency_id="hyperframes")
        component["primary_renderer"] = "HyperFrames"
        adapter = self._adapter(brief, "pass", dependency_id="hyperframes")

        self.assertIs(executor._validate_code_adapter(adapter, component), adapter)

    def test_local_canonical_reference_dependency_is_supported(self) -> None:
        brief = b"{}"
        dependency_id = "hd-talking-head-local-canonical"
        component = _code_component(brief, dependency_id=dependency_id)
        component["primary_renderer"] = "HyperFrames"
        adapter = self._adapter(brief, "pass", dependency_id=dependency_id)

        self.assertIs(executor._validate_code_adapter(adapter, component), adapter)

    def test_code_execution_rejects_missing_current_template_request(self) -> None:
        brief = b"{}"
        component = _code_component(brief)
        component["invocation_record"].pop("template_request", None)
        adapter = self._adapter(brief, "pass")
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor._validate_code_adapter(adapter, component)
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")

    def test_registered_remotion_engine_is_accepted_by_formal_adapter_gate(self) -> None:
        from dataclasses import replace
        brief = b"{}"
        component = _code_component(brief)
        record = json.loads((ROOT / "skill-development/hd-talking-head/references/verified-template-registry.json").read_text())["templates"][0]
        for field in ("template_origin", "template_id", "template_version", "verification_id",
                      "adaptation_level", "source_entrypoint", "source_sha256", "sample_sha256",
                      "semantic_families", "capacity"):
            component[field] = record[field]
        component["primary_renderer"] = "Remotion"
        component["invocation_record"]["template_request"] = {
            "semantic_family": "bar_chart", "information_units": 3,
            "numeric_values": [2, 5, 9], "numeric_scale": "linear",
        }
        adapter = replace(self._adapter(brief, "pass"), primary_renderer="Remotion")
        self.assertIs(executor._validate_code_adapter(adapter, component), adapter)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.job = _Job(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _adapter(
        self,
        brief: bytes,
        script: str,
        *,
        dependency_id: str = "html-video",
        timeout_seconds: float = 2.0,
        argv_template: tuple[str, ...] | None = None,
        request_only_values: tuple[str, ...] = (),
    ) -> executor.ReferenceProcessAdapter:
        root = self.root / f"dependency-{dependency_id}"
        root.mkdir(exist_ok=True)
        name = "render.py" if dependency_id == "html-video" else "skill.py"
        (root / name).write_text(script, encoding="utf-8")
        launcher = Path(sys.executable).resolve()
        return executor.ReferenceProcessAdapter(
            adapter_id="html-video-reference",
            dependency_id=dependency_id,
            approved_executor="approved:code_generated",
            dependency_root=root,
            entrypoint=name,
            entrypoint_sha256=_sha256((root / name).read_bytes()),
            producer_version="approved-version",
            primary_renderer="HyperFrames",
            renderer_version="approved-renderer",
            artifact_media_type="video",
            launcher=launcher,
            launcher_sha256=_sha256(launcher.read_bytes()),
            argv_template=argv_template
            or (
                "{launcher}",
                "{entrypoint}",
                "--brief",
                "{brief_path}",
                "--output",
                "{output_path}",
            ),
            brief_loader=lambda _job, _recipe, _component: brief,
            timeout_seconds=timeout_seconds,
            request_only_values=request_only_values,
            self_contained_wrapper=True,
        )

    def _execute(
        self,
        brief: bytes,
        adapter: executor.ReferenceProcessAdapter,
        *,
        dependency_id: str = "html-video",
        component_id: str = "code",
    ) -> executor.ComponentArtifact:
        return executor.execute_component(
            self.job,
            _request(
                _code_component(
                    brief,
                    dependency_id=dependency_id,
                    component_id=component_id,
                )
            ),
            adapters={
                "code_generated": {dependency_id: adapter},
                "artifact_probe": _artifact_probe(),
            },
        )

    def test_real_process_evidence_cross_binds_approved_invocation_and_output(self) -> None:
        brief = b'{"approved":"brief"}'
        script = (
            "from pathlib import Path\n"
            "import argparse, json, os, sys\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args()\n"
            "record={'pid':os.getpid(),'argv':sys.argv,'brief':Path(a.brief).read_text(),'invocation_id':os.environ['BROLL_INVOCATION_ID']}\n"
            "Path(a.output).write_text(json.dumps(record,sort_keys=True))\n"
        )
        artifact = self._execute(brief, self._adapter(brief, script))
        output_path = self.job.job_dir / artifact.job_path
        payload = json.loads(output_path.read_text())
        evidence = artifact.invocation_evidence

        self.assertEqual(evidence["dependency_id"], "html-video")
        self.assertEqual(evidence["kind"], "code_generated")
        self.assertEqual(
            evidence["approved_executor"], "approved:code_generated"
        )
        self.assertEqual(evidence["invocation_type"], "reference_process")
        self.assertEqual(evidence["approved_entrypoint"], "render.py")
        self.assertEqual(evidence["producer_version"], "approved-version")
        self.assertEqual(evidence["brief_sha256"], _sha256(brief))
        self.assertEqual(evidence["pid"], payload["pid"])
        self.assertEqual(evidence["invocation_id"], payload["invocation_id"])
        self.assertEqual(evidence["exit_code"], 0)
        self.assertFalse(evidence["timed_out"])
        self.assertEqual(evidence["primary_renderer"], "HyperFrames")
        self.assertEqual(evidence["renderer_version"], "approved-renderer")
        self.assertEqual(evidence["output_job_path"], artifact.job_path)
        self.assertEqual(evidence["output_sha256"], artifact.output_sha256)
        self.assertNotIn("FORGED-AND-MUST-NEVER-RUN", json.dumps(dict(evidence)))
        self.assertEqual(evidence["argv"].count("$DEPENDENCY/render.py"), 1)
        self.assertEqual(payload["brief"].encode(), brief)
        self.assertEqual(
            dict(artifact.artifact_contract),
            {"width": 1080, "height": 1920, "fps": 24, "alpha": True},
        )
        self.assertTrue(artifact.job_path.endswith(".mov"))

    def test_short_os_writes_preserve_frozen_entrypoint_and_process_output(self) -> None:
        brief = b'{"approved":"short-write"}'
        output = b"entrypoint-short-write-output"
        script = (
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args()\n"
            f"Path(a.output).write_bytes({output!r})\n"
        )
        original_write = os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return original_write(descriptor, payload[: max(1, len(payload) // 5)])

        with mock.patch.object(executor.os, "write", side_effect=short_write):
            artifact = self._execute(brief, self._adapter(brief, script))

        self.assertEqual((self.job.job_dir / artifact.job_path).read_bytes(), output)

    def _invoke_skill_primitive(self, brief, adapter):
        # Receipt unit checks do not register or enable a production source.
        request = _request(_code_component(brief, dependency_id=adapter.dependency_id))
        recipe = request.recipe
        component = recipe["components"][0]
        approval = _sha256(_canonical({"recipe": recipe, "component_id": request.component_id}))
        staging = "unit-skill-output.mp4"
        context = executor.AdapterContext(
            job_id=self.job.job_id, job_dir=self.job.job_dir, segment_id=recipe["segment_id"],
            strategy_revision=recipe["strategy_revision"], component_id=request.component_id,
            kind="code_generated", recipe=recipe, component=component,
            input_sha256=approval, approval_sha256=approval, source_path=None, source_sha256=None,
            staging_path=self.job.job_dir / staging, staging_job_path=staging,
            output_job_path="unused-unit-output.mp4",
        )
        return executor._run_skill_invocation(self.job, request, recipe, component, approval, adapter, context)

    def test_removed_broll_sources_are_rejected_before_any_process(self) -> None:
        brief = b"approved"
        marker = self.root / "removed-source-ran"
        for dependency_id in ("video-shotcraft", "stickman-video-director", "story-to-handdrawn-video"):
            with self.subTest(dependency_id=dependency_id):
                adapter = self._adapter(
                    brief, f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
                    dependency_id=dependency_id,
                )
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    self._execute(brief, adapter, dependency_id=dependency_id)
                self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
                self.assertFalse(marker.exists())
                self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_skill_primitive_validates_exact_remotion_receipt(self) -> None:
        brief = b"approved"
        def invoke(
            context: executor.AdapterContext, supplied_brief: bytes
        ) -> executor.SkillInvocationResult:
            self.assertEqual(supplied_brief, brief)
            context.staging_path.write_bytes(b"video")
            return executor.SkillInvocationResult(
                invocation_id="skill-invocation-001",
                receipt={
                    "schema_version": 1,
                    "invocation_id": "skill-invocation-001",
                    "dependency_id": "skill-unit-fixture",
                    "status": "completed",
                    "brief_sha256": _sha256(brief),
                    "staged_output_job_path": context.staging_job_path,
                    "output_sha256": _sha256(b"video"),
                    "producer_version": "approved-version",
                    "primary_renderer": "Remotion",
                    "renderer_version": "approved-renderer",
                },
                qa={"passed": True, "checks": ["skill_completed"]},
            )

        adapter = executor.SkillInvocationAdapter(
            adapter_id="unit-skill",
            dependency_id="skill-unit-fixture",
            approved_executor="approved:code_generated",
            entrypoint="skill.py",
            producer_version="approved-version",
            primary_renderer="Remotion",
            renderer_version="approved-renderer",
            artifact_media_type="video",
            brief_loader=lambda *_args: brief,
            invoker=invoke,
        )
        evidence, qa = self._invoke_skill_primitive(brief, adapter)
        self.assertEqual(evidence["invocation_type"], "skill_invocation")
        self.assertEqual(evidence["invocation_id"], "skill-invocation-001")
        self.assertEqual(evidence["receipt"]["status"], "completed")
        self.assertEqual(evidence["primary_renderer"], "Remotion")
        self.assertNotIn("HyperFrames", json.dumps(dict(evidence)))
        self.assertTrue(qa["passed"])

    def test_code_runtime_class_and_recipe_binding_must_match_before_staging(self) -> None:
        brief = b"approved"
        process = self._adapter(brief, "raise SystemExit('must not run')\n")

        def skill_invoke(*_args: object) -> executor.SkillInvocationResult:
            raise AssertionError("must not invoke")

        skill = executor.SkillInvocationAdapter(
            adapter_id="video-shotcraft-skill",
            dependency_id="video-shotcraft",
            approved_executor="approved:code_generated",
            entrypoint="skill.py",
            producer_version="approved-version",
            primary_renderer="Remotion",
            renderer_version="approved-renderer",
            artifact_media_type="video",
            brief_loader=lambda *_args: brief,
            invoker=skill_invoke,
        )
        cases = (
            ("video-shotcraft", process),
            ("html-video", skill),
            (
                "html-video",
                executor.ReferenceProcessAdapter(
                    **{**process.__dict__, "approved_executor": "other-runtime"}
                ),
            ),
            (
                "html-video",
                executor.ReferenceProcessAdapter(
                    **{**process.__dict__, "primary_renderer": "Remotion"}
                ),
            ),
        )
        for dependency_id, adapter in cases:
            with self.subTest(dependency_id=dependency_id, adapter=type(adapter).__name__):
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    executor.execute_component(
                        self.job,
                        _request(_code_component(brief, dependency_id=dependency_id)),
                        adapters={
                            "code_generated": {dependency_id: adapter},
                            "artifact_probe": _artifact_probe(),
                        },
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND"
                )
                self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_brief_loader_receives_frozen_inputs_and_mutation_invalidates_execution(self) -> None:
        brief = b"approved"
        request = _request(_code_component(brief))
        adapter = self._adapter(brief, "raise SystemExit('must not run')\n")

        def loader(_job: object, recipe: object, component: object) -> bytes:
            with self.assertRaises(TypeError):
                recipe["strategy_revision"] = 999
            with self.assertRaises(TypeError):
                component["brief_sha256"] = "0" * 64
            request.recipe["components"][0]["brief_sha256"] = "1" * 64
            return brief

        adapter = executor.ReferenceProcessAdapter(
            **{**adapter.__dict__, "brief_loader": loader}
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "code_generated": {"html-video": adapter},
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_SCHEMA_INVALID")
        self.assertFalse(
            (self.job.job_dir / "08-visual-assets/components/seg-001/code-r7.mp4").exists()
        )

    def test_skill_receipt_is_exact_approved_json_and_must_identify_invocation(self) -> None:
        brief = b"approved"
        invalid = (
            executor.SkillInvocationResult(
                invocation_id="",
                receipt={"status": "completed"},
                qa={"passed": True, "checks": ["skill_completed"]},
            ),
            executor.SkillInvocationResult(
                invocation_id="skill-1",
                receipt={"authorization": "request-only"},
                qa={"passed": True, "checks": ["skill_completed"]},
            ),
            executor.SkillInvocationResult(
                invocation_id="skill-1",
                receipt={"status": "completed", 1: "non-string-key"},
                qa={"passed": True, "checks": ["skill_completed"]},
            ),
        )
        for result in invalid:
            with self.subTest(result=result):
                def invoke(
                    context: executor.AdapterContext, _brief: bytes
                ) -> executor.SkillInvocationResult:
                    context.staging_path.write_bytes(b"video")
                    return result

                adapter = executor.SkillInvocationAdapter(
                    adapter_id="unit-skill",
                    dependency_id="skill-unit-fixture",
                    approved_executor="approved:code_generated",
                    entrypoint="skill.py",
                    producer_version="approved-version",
                    primary_renderer="Remotion",
                    renderer_version="approved-renderer",
                    artifact_media_type="video",
                    brief_loader=lambda *_args: brief,
                    invoker=invoke,
                )
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    self._invoke_skill_primitive(brief, adapter)
                self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

    def test_skill_receipt_hash_and_approved_binding_are_cross_checked(self) -> None:
        brief = b"approved"

        def invoke(
            context: executor.AdapterContext, _brief: bytes
        ) -> executor.SkillInvocationResult:
            context.staging_path.write_bytes(b"video")
            return executor.SkillInvocationResult(
                invocation_id="skill-cross-check",
                receipt={
                    "schema_version": 1,
                    "invocation_id": "skill-cross-check",
                    "dependency_id": "skill-unit-fixture",
                    "status": "completed",
                    "brief_sha256": _sha256(brief),
                    "staged_output_job_path": context.staging_job_path,
                    "output_sha256": "0" * 64,
                    "producer_version": "approved-version",
                    "primary_renderer": "Remotion",
                    "renderer_version": "approved-renderer",
                },
                qa={"passed": True, "checks": ["skill_completed"]},
            )

        adapter = executor.SkillInvocationAdapter(
            adapter_id="unit-skill",
            dependency_id="skill-unit-fixture",
            approved_executor="approved:code_generated",
            entrypoint="skill.py",
            producer_version="approved-version",
            primary_renderer="Remotion",
            renderer_version="approved-renderer",
            artifact_media_type="video",
            brief_loader=lambda *_args: brief,
            invoker=invoke,
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._invoke_skill_primitive(brief, adapter)
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

    def test_reference_process_requires_explicit_self_contained_wrapper(self) -> None:
        brief = b"approved"
        package = self.root / "dependency-html-video" / "helper.py"
        package.parent.mkdir(exist_ok=True)
        package.write_text("VALUE = b'imported'\n", encoding="utf-8")
        adapter = self._adapter(
            brief,
            "from helper import VALUE\n"
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(VALUE)\n",
        )
        adapter = executor.ReferenceProcessAdapter(
            **{**adapter.__dict__, "self_contained_wrapper": False}
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, adapter)
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
        self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_code_adapter_bindings_require_exact_strings_and_path_objects(self) -> None:
        brief = b"approved"
        fields = (
            "dependency_id",
            "approved_executor",
            "entrypoint",
            "producer_version",
            "primary_renderer",
            "renderer_version",
            "artifact_media_type",
            "dependency_root",
            "launcher",
        )
        for field in fields:
            with self.subTest(field=field):
                marker = self.root / f"invalid-{field}-ran"
                adapter = self._adapter(
                    brief,
                    "from pathlib import Path\nimport argparse\n"
                    "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
                    "a=p.parse_args(); "
                    f"Path({str(marker)!r}).write_text('ran'); "
                    "Path(a.output).write_bytes(b'unused')\n",
                )
                original = getattr(adapter, field)
                invalid = (
                    str(original)
                    if field in {"dependency_root", "launcher"}
                    else _Text(original)
                )
                adapter = executor.ReferenceProcessAdapter(
                    **{**adapter.__dict__, field: invalid}
                )
                with self.assertRaises(
                    executor.BrollComponentExecutionError
                ) as caught:
                    self._execute(
                        brief,
                        adapter,
                        component_id=f"invalid-{field}",
                    )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND"
                )
                self.assertFalse(marker.exists())
                self.assertFalse(
                    (self.job.job_dir / "08-visual-assets").exists()
                )

    def test_skill_binding_strings_are_exact_before_invoker(self) -> None:
        brief = b"approved"
        marker = self.root / "invalid-skill-ran"

        def invoke(
            context: executor.AdapterContext, _brief: bytes
        ) -> executor.SkillInvocationResult:
            marker.write_text("ran")
            context.staging_path.write_bytes(b"unused")
            raise AssertionError("must not invoke")

        adapter = executor.SkillInvocationAdapter(
            adapter_id="video-shotcraft-skill",
            dependency_id="video-shotcraft",
            approved_executor="approved:code_generated",
            entrypoint="skill.py",
            producer_version="approved-version",
            primary_renderer=_Text("Remotion"),
            renderer_version="approved-renderer",
            artifact_media_type="video",
            brief_loader=lambda *_args: brief,
            invoker=invoke,
        )
        self.assertFalse(executor._common_code_binding_valid(
            adapter, _code_component(brief, dependency_id=adapter.dependency_id)
        ))
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_code_component(brief, dependency_id="video-shotcraft")),
                adapters={
                    "code_generated": {"video-shotcraft": adapter},
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
        self.assertFalse(marker.exists())
        self.assertFalse((self.job.job_dir / "08-visual-assets").exists())

    def test_process_replay_requires_exact_canonical_argv(self) -> None:
        brief = b"approved"
        output = b"argv-output"
        component_id = "argv-bound"
        adapter = self._adapter(
            brief,
            "from pathlib import Path\nimport argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            f"a=p.parse_args(); Path(a.output).write_bytes({output!r})\n",
        )
        self._execute(
            brief, adapter, component_id=component_id
        )
        receipt = self.job.job_dir / (
            "08-visual-assets/components/seg-001/"
            f".{component_id}-r7.transaction.json"
        )
        baseline = json.loads(receipt.read_text())
        mutations = (
            lambda argv: argv.__setitem__(0, 1),
            lambda argv: argv.__setitem__(1, ""),
            lambda argv: argv.__setitem__(1, "$DEPENDENCY/other.py"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = copy.deepcopy(baseline)
                mutate(record["artifact"]["invocation_evidence"]["argv"])
                receipt.write_bytes(_canonical(record) + b"\n")
                with mock.patch.object(
                    executor,
                    "_freeze_process_binding",
                    side_effect=AssertionError("invalid replay touched runtime"),
                ):
                    with self.assertRaises(
                        executor.BrollComponentExecutionError
                    ) as caught:
                        self._execute(
                            brief, adapter, component_id=component_id
                        )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_RENDER_FAILED"
                )

    def test_canonical_argv_uses_template_positions_and_hides_registered_literals(
        self,
    ) -> None:
        brief = b"approved"
        request_only_literal = "registered-request-only-literal"
        output = b"canonical-argv-output"
        template = (
            "{launcher}",
            "{entrypoint}",
            "--brief",
            "{brief_path}",
            "--output",
            "{output_path}",
            request_only_literal,
            "-",
        )
        adapter = self._adapter(
            brief,
            "from pathlib import Path\nimport argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a,rest=p.parse_known_args()\n"
            f"assert rest == {[request_only_literal, '-']!r}\n"
            f"Path(a.output).write_bytes({output!r})\n",
            argv_template=template,
            request_only_values=(request_only_literal,),
        )

        artifact = self._execute(
            brief, adapter, component_id="canonical-request-only"
        )
        receipt = self.job.job_dir / (
            "08-visual-assets/components/seg-001/"
            ".canonical-request-only-r7.transaction.json"
        )
        raw = receipt.read_text()
        record = json.loads(raw)
        expected_argv = [
            "$LAUNCHER",
            "$DEPENDENCY/render.py",
            "--brief",
            "$JOB/brief.json",
            "--output",
            f"$JOB/{record['adapter_staging_job_path']}",
            "$REQUEST_ONLY[0]",
            "-",
        ]
        self.assertEqual(
            list(artifact.invocation_evidence["argv"]), expected_argv
        )
        self.assertNotIn(request_only_literal, raw)
        self.assertNotIn(request_only_literal, json.dumps(dict(artifact)))
        binding = record["adapter_binding"]
        self.assertEqual(
            binding["argv_template"][-2:],
            [
                {
                    "index": 6,
                    "role": "literal",
                    "value": "$REQUEST_ONLY[0]",
                },
                {"index": 7, "role": "literal", "value": "-"},
            ],
        )
        self.assertEqual(
            binding["argv_template_sha256"], _sha256(_canonical(list(template)))
        )
        with mock.patch.object(
            executor,
            "_freeze_process_binding",
            side_effect=AssertionError("replay touched process runtime"),
        ):
            replay = self._execute(
                brief, adapter, component_id="canonical-request-only"
            )
        self.assertEqual(
            replay.invocation_evidence["argv"], artifact.invocation_evidence["argv"]
        )

    def test_replay_rejects_canonical_template_or_raw_template_hash_changes(
        self,
    ) -> None:
        brief = b"approved"
        component_id = "canonical-binding"
        adapter = self._adapter(
            brief,
            "from pathlib import Path\nimport argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args(); Path(a.output).write_bytes(b'canonical')\n",
        )
        self._execute(brief, adapter, component_id=component_id)
        receipt = self.job.job_dir / (
            "08-visual-assets/components/seg-001/"
            f".{component_id}-r7.transaction.json"
        )
        baseline = json.loads(receipt.read_text())
        mutations = (
            lambda binding: binding["argv_template"][2].__setitem__(
                "value", "--changed"
            ),
            lambda binding: binding.__setitem__(
                "argv_template_sha256", "0" * 64
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = copy.deepcopy(baseline)
                mutate(record["adapter_binding"])
                receipt.write_bytes(_canonical(record) + b"\n")
                with mock.patch.object(
                    executor,
                    "_freeze_process_binding",
                    side_effect=AssertionError("invalid replay touched runtime"),
                ):
                    with self.assertRaises(
                        executor.BrollComponentExecutionError
                    ) as caught:
                        self._execute(
                            brief, adapter, component_id=component_id
                        )
                self.assertEqual(
                    caught.exception.error_code, "BROLL_RENDER_FAILED"
                )
        receipt.write_bytes(_canonical(baseline) + b"\n")

    def test_published_process_replay_does_not_freeze_dependency_runtime(self) -> None:
        brief = b"approved"
        adapter = self._adapter(
            brief,
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(b'replay')\n",
        )
        first = self._execute(brief, adapter)
        with mock.patch.object(
            executor,
            "_freeze_process_binding",
            side_effect=AssertionError("published replay touched runtime"),
        ):
            second = self._execute(brief, adapter)
        self.assertEqual(second.output_sha256, first.output_sha256)

    def test_capability_name_without_callable_bound_adapter_is_unbound(self) -> None:
        brief = b"approved"
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_code_component(brief)),
                adapters={
                    "code_generated": {"html-video": {"directory": "exists"}},
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")

    def test_recipe_entrypoint_command_and_fake_record_never_control_process(self) -> None:
        brief = b"approved"
        marker = self.root / "must-not-exist"
        component = _code_component(brief)
        component["invocation_record"] = {
            **component["invocation_record"],
            "argv": [
                sys.executable,
                component["entrypoint"],
                "producer_command",
                str(marker),
            ],
            "exit_code": 0,
        }
        adapter = self._adapter(
            brief,
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args(); Path(a.output).write_bytes(b'ok')\n",
        )
        artifact = executor.execute_component(
            self.job,
            _request(component),
            adapters={
                "code_generated": {"html-video": adapter},
                "artifact_probe": _artifact_probe(),
            },
        )
        self.assertFalse(marker.exists())
        self.assertNotIn(
            "producer_command", json.dumps(dict(artifact.invocation_evidence))
        )

    def test_dependency_root_entrypoint_and_template_are_strictly_contained_and_bound_once(
        self,
    ) -> None:
        brief = b"approved"
        safe_script = "raise SystemExit('must not launch')\n"
        cases: list[executor.ReferenceProcessAdapter] = []
        outside = self.root / "outside.py"
        outside.write_text(safe_script)
        root = self.root / "root"
        root.mkdir()
        (root / "render.py").symlink_to(outside)
        normal = self._adapter(brief, safe_script)
        cases.append(
            executor.ReferenceProcessAdapter(
                **{
                    **normal.__dict__,
                    "dependency_root": root,
                    "entrypoint_sha256": _sha256(outside.read_bytes()),
                }
            )
        )
        real_parent = self.root / "real-parent"
        real_dependency = real_parent / "dependency"
        real_dependency.mkdir(parents=True)
        (real_dependency / "render.py").write_text(safe_script, encoding="utf-8")
        root_alias = self.root / "root-alias"
        root_alias.symlink_to(real_parent, target_is_directory=True)
        cases.extend(
            [
                executor.ReferenceProcessAdapter(
                    **{
                        **normal.__dict__,
                        "entrypoint": "../outside.py",
                    }
                ),
                executor.ReferenceProcessAdapter(
                    **{
                        **normal.__dict__,
                        "argv_template": (
                            "{launcher}",
                            "{entrypoint}",
                            "{entrypoint}",
                            "{brief_path}",
                            "{output_path}",
                        ),
                    }
                ),
                executor.ReferenceProcessAdapter(
                    **{
                        **normal.__dict__,
                        "argv_template": (
                            "{launcher}",
                            "{entrypoint}",
                            "{brief_path}",
                        ),
                    }
                ),
                executor.ReferenceProcessAdapter(
                    **{
                        **normal.__dict__,
                        "argv_template": (
                            "{launcher}",
                            "{entrypoint}",
                            str(normal.dependency_root / normal.entrypoint),
                            "{brief_path}",
                            "{output_path}",
                        ),
                    }
                ),
                executor.ReferenceProcessAdapter(
                    **{
                        **normal.__dict__,
                        "dependency_root": root_alias / "dependency",
                    }
                ),
            ]
        )

        for adapter in cases:
            with self.subTest(entrypoint=adapter.entrypoint, argv=adapter.argv_template):
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    self._execute(brief, adapter)
                self.assertEqual(
                    caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND"
                )

    def test_brief_loader_swap_cannot_change_frozen_approved_entrypoint(self) -> None:
        brief = b"approved"
        marker = self.root / "outside-ran"
        adapter = self._adapter(
            brief,
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(b'approved-output')\n",
        )
        outside = self.root / "outside.py"
        outside.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
            encoding="utf-8",
        )

        def swapping_loader(*_args: object) -> bytes:
            entrypoint = adapter.dependency_root / adapter.entrypoint
            entrypoint.unlink()
            entrypoint.symlink_to(outside)
            return brief

        adapter = executor.ReferenceProcessAdapter(
            **{**adapter.__dict__, "brief_loader": swapping_loader}
        )

        artifact = self._execute(brief, adapter)
        self.assertFalse(marker.exists())
        self.assertEqual(
            (self.job.job_dir / artifact.job_path).read_bytes(), b"approved-output"
        )

    def test_entrypoint_path_swap_at_process_start_rejects_without_running_replacement(self) -> None:
        brief = b"approved"
        approved = b"approved-frozen-output"
        marker = self.root / "replacement-entrypoint-ran"
        script = (
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
            "a=p.parse_args(); Path(a.output).write_bytes("
            f"{approved!r})\n"
        )
        adapter = self._adapter(brief, script)
        real_popen = subprocess.Popen

        def swapping_popen(argv: object, *args: object, **kwargs: object) -> object:
            snapshots = list(
                self.job.job_dir.rglob(".staging/*/approved-entrypoint")
            )
            self.assertEqual(len(snapshots), 1)
            approved = snapshots[0]
            approved.rename(approved.with_name("moved-entrypoint"))
            approved.write_text(
                "from pathlib import Path\n"
                "import argparse\n"
                "p=argparse.ArgumentParser(); p.add_argument('--brief'); p.add_argument('--output')\n"
                "a=p.parse_args(); Path(a.output).write_bytes(b'replacement')\n"
                f"Path({str(marker)!r}).write_text('ran')\n",
                encoding="utf-8",
            )
            return real_popen(argv, *args, **kwargs)

        with mock.patch.object(
            executor.subprocess, "Popen", side_effect=swapping_popen
        ):
            with self.assertRaises(
                executor.BrollComponentExecutionError
            ) as caught:
                self._execute(brief, adapter)

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
        self.assertFalse(marker.exists())
        self.assertEqual(
            list(
                self.job.job_dir.glob(
                    "08-visual-assets/components/seg-001/code-r7.*"
                )
            ),
            [],
        )

    def test_brief_loader_launcher_replacement_is_rejected_before_process_start(self) -> None:
        brief = b"approved"
        marker = self.root / "replacement-launcher-ran"
        adapter = self._adapter(brief, "raise SystemExit('must not run')\n")
        launcher = self.root / "approved-launcher"
        launcher.write_bytes(b"approved-launcher")
        launcher.chmod(0o700)
        adapter = executor.ReferenceProcessAdapter(
            **{
                **adapter.__dict__,
                "launcher": launcher,
                "launcher_sha256": _sha256(launcher.read_bytes()),
            }
        )
        replacement = self.root / "replacement-launcher"
        replacement.write_text(
            "#!/bin/sh\n" + f"touch {str(marker)!r}\n", encoding="utf-8"
        )
        replacement.chmod(0o700)

        def loader(*_args: object) -> bytes:
            launcher.unlink()
            launcher.symlink_to(replacement)
            return brief

        adapter = executor.ReferenceProcessAdapter(
            **{**adapter.__dict__, "brief_loader": loader}
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, adapter)
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")
        self.assertFalse(marker.exists())

    def test_cleanup_failure_preserves_more_specific_dependency_error(self) -> None:
        brief = b"approved"
        adapter = self._adapter(brief, "raise SystemExit('original')\n")
        outside = self.root / "outside.py"
        outside.write_text("raise SystemExit('outside')\n", encoding="utf-8")

        def swapping_loader(*_args: object) -> bytes:
            entrypoint = adapter.dependency_root / adapter.entrypoint
            entrypoint.unlink()
            entrypoint.symlink_to(outside)
            return brief

        adapter = executor.ReferenceProcessAdapter(
            **{**adapter.__dict__, "brief_loader": swapping_loader}
        )

        with mock.patch.object(
            executor,
            "_remove_tree_at",
            side_effect=OSError("injected cleanup failure"),
        ):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                self._execute(brief, adapter)

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

    def test_startup_nonzero_missing_and_partial_outputs_are_render_failures(self) -> None:
        brief = b"approved"
        scripts = {
            "nonzero": "raise SystemExit(7)\n",
            "missing": "pass\n",
            "partial": (
                "from pathlib import Path\nimport sys\n"
                "Path(sys.argv[-1]).write_bytes(b'partial')\nraise SystemExit(9)\n"
            ),
        }
        for name, script in scripts.items():
            with self.subTest(case=name):
                adapter = self._adapter(brief, script)
                with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                    self._execute(brief, adapter)
                self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
                self.assertFalse(
                    (self.job.job_dir / "08-visual-assets/components/seg-001/code-r7.mp4").exists()
                )

        missing_executable = self._adapter(brief, "pass\n")
        missing_executable = executor.ReferenceProcessAdapter(
            **{
                **missing_executable.__dict__,
                "argv_template": (
                    str(self.root / "missing-executable"),
                    "{entrypoint}",
                    "{brief_path}",
                    "{output_path}",
                ),
            }
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, missing_executable)
        self.assertEqual(caught.exception.error_code, "BROLL_DEPENDENCY_UNBOUND")

    def test_timeout_terminates_the_entire_process_group_including_descendants(self) -> None:
        brief = b"approved"
        sentinel = self.root / "descendant-survived"
        child_code = (
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(0.8); Path(" + repr(str(sentinel)) + ").write_text('bad')"
        )
        script = (
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable,'-c',{child_code!r}])\n"
            "time.sleep(10)\n"
        )
        adapter = self._adapter(brief, script, timeout_seconds=0.15)

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, adapter)
        time.sleep(1.0)

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
        self.assertFalse(sentinel.exists())
        self.assertTrue(caught.exception.evidence["timed_out"])

    def test_success_parent_with_lingering_descendant_is_killed_before_probe(self) -> None:
        brief = b"approved"
        sentinel = self.root / "descendant-mutated-output"
        child_code = (
            "import signal,time,sys; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(0.8); Path(sys.argv[1]).write_bytes(b'bad'); "
            f"Path({str(sentinel)!r}).write_text('survived')"
        )
        script = (
            "from pathlib import Path\nimport subprocess,sys\n"
            "Path(sys.argv[-1]).write_bytes(b'good')\n"
            f"subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[-1]])\n"
        )
        artifact = self._execute(brief, self._adapter(brief, script))
        time.sleep(1.0)
        self.assertEqual((self.job.job_dir / artifact.job_path).read_bytes(), b"good")
        self.assertFalse(sentinel.exists())
        self.assertTrue(artifact.invocation_evidence["descendants_terminated"])

    def test_unresolved_success_process_group_is_render_failure_and_never_publishes(self) -> None:
        brief = b"approved"
        script = (
            "from pathlib import Path\nimport subprocess,sys,time\n"
            "Path(sys.argv[-1]).write_bytes(b'good')\n"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])\n"
        )
        adapter = self._adapter(brief, script)
        real_killpg = os.killpg

        def denied(pid: int, sig: int) -> None:
            if sig == signal.SIGTERM:
                real_killpg(pid, signal.SIGKILL)
                raise PermissionError("denied")
            real_killpg(pid, sig)

        with mock.patch.object(executor.os, "killpg", side_effect=denied):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                self._execute(brief, adapter)
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
        self.assertTrue(caught.exception.evidence["unresolved_process_group"])
        self.assertFalse(
            (self.job.job_dir / "08-visual-assets/components/seg-001/code-r7.mp4").exists()
        )

    def test_process_output_is_bounded_and_environment_is_minimal_offline(self) -> None:
        brief = b"approved"
        noisy = self._adapter(
            brief,
            "import sys\nsys.stdout.write('x' * (2 * 1024 * 1024))\n",
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, noisy)
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

        script = (
            "from pathlib import Path\nimport json,os,sys\n"
            "Path(sys.argv[-1]).write_text(json.dumps(dict(os.environ),sort_keys=True))\n"
        )
        with mock.patch.dict(
            os.environ, {"PROVIDER_RUNTIME_VALUE": "must-not-record"}
        ):
            artifact = self._execute(
                brief, self._adapter(brief, script), component_id="code-env"
            )
        environment = json.loads((self.job.job_dir / artifact.job_path).read_text())
        self.assertEqual(environment["BROLL_OFFLINE"], "1")
        self.assertEqual(environment["NO_PROXY"], "*")
        self.assertNotIn("PROVIDER_RUNTIME_VALUE", environment)

    def test_kill_permission_failure_never_reports_success(self) -> None:
        brief = b"approved"
        adapter = self._adapter(brief, "import time; time.sleep(10)\n", timeout_seconds=0.05)
        real_killpg = os.killpg

        def denied(pid: int, sig: int) -> None:
            if sig == signal.SIGTERM:
                real_killpg(pid, signal.SIGKILL)
                raise PermissionError("denied")
            real_killpg(pid, sig)

        with mock.patch.object(executor.os, "killpg", side_effect=denied):
            with self.assertRaises(executor.BrollComponentExecutionError) as caught:
                self._execute(brief, adapter)

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")
        self.assertNotIn("success", str(caught.exception).lower())

    def test_process_group_wait_rechecks_transient_denied_until_gone(self) -> None:
        states = mock.Mock(
            side_effect=((True, True), (False, False))
        )
        with mock.patch.object(
            executor, "_group_exists", states
        ), mock.patch.object(
            executor.time,
            "monotonic",
            side_effect=(0.0, 0.0, 0.01),
        ), mock.patch.object(executor.time, "sleep"):
            gone = executor._wait_group_gone(12345, 0.1)

        self.assertTrue(gone)
        self.assertEqual(states.call_count, 2)

    def test_process_group_wait_keeps_persistent_denied_until_deadline(self) -> None:
        states = mock.Mock(return_value=(True, True))
        with mock.patch.object(
            executor, "_group_exists", states
        ), mock.patch.object(
            executor.time,
            "monotonic",
            side_effect=(0.0, 0.0, 0.01, 0.02, 0.03),
        ), mock.patch.object(executor.time, "sleep"):
            gone = executor._wait_group_gone(12345, 0.03)

        self.assertFalse(gone)
        self.assertEqual(states.call_count, 4)

    def test_brief_hash_output_probe_and_empty_output_stop_explicitly(self) -> None:
        approved = b"approved"
        script = (
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(b'output')\n"
        )
        wrong_brief = self._adapter(b"wrong", script)
        wrong_brief = executor.ReferenceProcessAdapter(
            **{**wrong_brief.__dict__, "brief_loader": lambda *_args: b"wrong"}
        )
        request = _request(_code_component(approved))
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                request,
                adapters={
                    "code_generated": {"html-video": wrong_brief},
                    "artifact_probe": _artifact_probe(),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

        bad_probe = self._adapter(approved, script)
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_code_component(approved)),
                adapters={
                    "code_generated": {"html-video": bad_probe},
                    "artifact_probe": executor.ArtifactProbe(
                        probe_id="bad-probe",
                        probe_version="1",
                        probe=lambda *_args: {"passed": False},
                    ),
                },
            )
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

        empty = self._adapter(
            approved,
            "from pathlib import Path\nimport sys\nPath(sys.argv[-1]).write_bytes(b'')\n",
        )
        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(approved, empty)
        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

    def test_probe_cannot_mutate_output_after_validating_different_bytes(self) -> None:
        brief = b"approved"
        script = (
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(b'valid-before-probe')\n"
        )
        adapter = self._adapter(brief, script)

        def mutating_probe(
            path: Path, _media_type: str, contract: object
        ) -> dict[str, object]:
            path.write_bytes(b"mutated-after-validation")
            return {
                "passed": True,
                "width": contract["width"],
                "height": contract["height"],
                "fps": contract["fps"],
                "alpha": contract["alpha"],
            }

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            executor.execute_component(
                self.job,
                _request(_code_component(brief)),
                adapters={
                    "code_generated": {"html-video": adapter},
                    "artifact_probe": executor.ArtifactProbe(
                        probe_id="mutating-probe",
                        probe_version="1",
                        probe=mutating_probe,
                    ),
                },
            )

        self.assertEqual(caught.exception.error_code, "BROLL_RENDER_FAILED")

    def test_process_logs_and_argv_filter_request_only_values_from_failure_evidence(self) -> None:
        brief = b"approved"
        request_only_value = "SUPER-REQUEST-ONLY-VALUE"
        script = (
            "import sys\n"
            f"print({request_only_value!r})\n"
            f"print({request_only_value!r}, file=sys.stderr)\n"
            "raise SystemExit(4)\n"
        )
        adapter = self._adapter(
            brief,
            script,
            argv_template=(
                "{launcher}",
                "{entrypoint}",
                request_only_value,
                "{brief_path}",
                "{output_path}",
            ),
            request_only_values=(request_only_value,),
        )

        with self.assertRaises(executor.BrollComponentExecutionError) as caught:
            self._execute(brief, adapter)

        serialized = json.dumps(dict(caught.exception.evidence), sort_keys=True)
        self.assertNotIn(request_only_value, str(caught.exception))
        self.assertNotIn(request_only_value, serialized)
        self.assertNotIn(str(self.job.job_dir), serialized)
        self.assertNotIn(str(adapter.dependency_root), serialized)

    def test_final_output_is_job_relative_regular_and_no_replace(self) -> None:
        brief = b"approved"
        script = (
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_bytes(b'output')\n"
        )
        artifact = self._execute(brief, self._adapter(brief, script))
        output = self.job.job_dir / artifact.job_path
        metadata = output.stat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_nlink, 1)
        self.assertTrue(output.is_relative_to(self.job.job_dir))


if __name__ == "__main__":
    unittest.main()


class ReferenceMediaBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def test_empty_verified_project_file_is_frozen_but_empty_media_is_rejected(self):
        from types import SimpleNamespace
        job = _Job(self.directory)
        path = job.job_dir / 'fonts.css'; path.write_bytes(b'')
        digest = hashlib.sha256(b'').hexdigest()
        item = executor.ReferenceProcessMedia('source', path.name, digest)
        adapter = SimpleNamespace(media_loader=lambda *_: (item,))
        pinned = executor._job_context(job)
        try:
            for allowed, should_pass in ((set(), False), ({(path.name, digest)}, True),
                                         ({(path.name, '0' * 64)}, False)):
                with tempfile.TemporaryDirectory() as tmp:
                    nonce_fd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        with mock.patch.object(executor, '_wake_empty_project_files', return_value=allowed):
                            if should_pass:
                                manifest_fd, media_fds = executor._freeze_reference_media(
                                    adapter=adapter, job=job, pinned_job=pinned, recipe={},
                                    component={}, brief=b'{}', nonce_fd=nonce_fd)
                                self.assertEqual(os.fstat(media_fds[0]).st_size, 0)
                                for fd in (manifest_fd, *media_fds): os.close(fd)
                            else:
                                with self.assertRaises(executor.BrollComponentExecutionError):
                                    executor._freeze_reference_media(adapter=adapter, job=job,
                                        pinned_job=pinned, recipe={}, component={}, brief=b'{}', nonce_fd=nonce_fd)
                    finally:
                        os.close(nonce_fd)
        finally:
            pinned.close()

    def test_reference_media_freezes_more_than_eight_and_closes_on_budget_or_fd_failure(self) -> None:
        job = _Job(self.directory)
        records = []
        for index in range(9):
            data = f"media-{index}".encode()
            path = job.job_dir / f"media-{index}.bin"
            path.write_bytes(data)
            records.append(executor.ReferenceProcessMedia(
                media_ref=f"media-{index}", job_path=path.name,
                sha256=hashlib.sha256(data).hexdigest()))
        from types import SimpleNamespace
        adapter = SimpleNamespace(media_loader=lambda *_args: tuple(records))
        pinned = executor._job_context(job)
        try:
            nonce = self.directory / "nonce-many"
            nonce.mkdir(); nonce_fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY)
            manifest_fd = media_fds = None
            try:
                manifest_fd, media_fds = executor._freeze_reference_media(
                    adapter=adapter, job=job, pinned_job=pinned, recipe={},
                    component={}, brief=b'{}', nonce_fd=nonce_fd)
                self.assertEqual(len(media_fds), 9)
                self.assertTrue(all(os.fstat(fd).st_size > 0 for fd in media_fds))
            finally:
                for fd in (() if manifest_fd is None else (manifest_fd,)) + (() if media_fds is None else tuple(media_fds)):
                    os.close(fd)
                os.close(nonce_fd)

            for label, patcher in (
                ("budget", mock.patch("edit.hd.tools.broll_component_executor._MAX_REFERENCE_MEDIA_TOTAL_BYTES", 1)),
                ("fd", mock.patch("edit.hd.tools.broll_component_executor.resource.getrlimit", return_value=(1, 1))),
            ):
                nonce = self.directory / f"nonce-{label}"
                nonce.mkdir(); nonce_fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    with patcher, self.assertRaises(executor.BrollComponentExecutionError):
                        executor._freeze_reference_media(
                            adapter=adapter, job=job, pinned_job=pinned, recipe={},
                            component={}, brief=b'{}', nonce_fd=nonce_fd)
                    self.assertEqual(list(nonce.iterdir()), [])
                finally:
                    os.close(nonce_fd)
        finally:
            pinned.close()

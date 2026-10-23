from __future__ import annotations

import copy
from collections import Counter
from dataclasses import FrozenInstanceError
import hashlib
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from edit.hd.tools import broll_media, visual_strategy


class _Job:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.job_dir = root / "job"
        self.job_dir.mkdir()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_window(index: int = 0) -> dict[str, object]:
    return {
        "start_frame": 0,
        "end_frame": 72,
        "z_index": index * 10,
        "layout_slot": "main" if index == 0 else "annotation",
        "opacity": 1.0,
        "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
    }


def _binding(kind: str, path: str | None = None) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "local_material": {
            "material_id": "material-001",
            "job_path": path or "00-user-provided/material-001.png",
            "sha256": "1" * 64,
        },
        "official_material": {
            "source_id": "official-001",
            "publisher": "Example Institute",
            "source_url": "https://example.org/report",
            "snapshot_path": path or "00-user-provided/official-001.pdf",
            "fetched_at": "2026-08-31T12:00:00+08:00",
            "sha256": "2" * 64,
        },
        "external_stock": {
            "provider": "Pexels",
            "provider_asset_id": "stock-001",
            "author": "Example Author",
            "asset_page": "https://www.pexels.com/video/stock-001",
            "job_path": path or "07-visual-direction/stock/stock-001.mp4",
            "license_snapshot": "07-visual-direction/licenses/stock-001.json",
            "downloaded_at": "2026-08-31T12:00:00+08:00",
            "sha256": "3" * 64,
        },
        "code_generated": {
            "producer_type": "dependency",
            "dependency_id": "html-video",
            "entrypoint": "packages/adapter-hyperframes/src/render.ts",
            "producer_version": "renderer-v1",
            "brief_sha256": "4" * 64,
            "invocation_record": {
                "argv": ["node", "packages/adapter-hyperframes/src/render.ts"],
                "exit_code": 0,
                "template_request": {
                    "semantic_family": "explanation", "information_units": 3,
                    "numeric_values": [], "numeric_scale": "not_applicable",
                },
            },
            "primary_renderer": "HyperFrames",
            "renderer_version": "1.2.3",
            # Synthetic resolver fixture, not a verified third-party template.
            "template_origin": "custom_fallback",
            "template_id": "media-resolver-fixture",
            "template_version": "1",
            "verification_id": "7" * 64,
            "adaptation_level": "structural",
            "source_entrypoint": "templates/media-resolver-fixture.html",
            "source_sha256": "8" * 64,
            "sample_sha256": "9" * 64,
            "semantic_families": ["explanation"],
            "capacity": {"min_units": 1, "max_units": 7},
        },
        "ai_generated": {
            "provider": "xAI",
            "model": "grok-imagine-video",
            "endpoint_id": "video-generation",
            "prompt_sha256": "5" * 64,
            "generation_id": "generation-001",
            "sha256": "6" * 64,
        },
    }
    return copy.deepcopy(values[kind])


def _component(
    component_id: str,
    kind: str,
    *,
    path: str | None = None,
    index: int = 0,
    media_type: str | None = None,
) -> dict[str, object]:
    return {
        "component_id": component_id,
        "kind": kind,
        "semantic_role": "explanation",
        "layer_role": "base" if index == 0 else "annotation",
        "executor": "approved-executor",
        "media_type": media_type or ("animation" if kind == "code_generated" else "image"),
        "render_window": _render_window(index),
        "artifact_contract": {
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "alpha": kind == "code_generated",
        },
        **_binding(kind, path),
    }


def _recipe(components: list[dict[str, object]]) -> dict[str, object]:
    mode = "none" if not components else "single" if len(components) == 1 else "hybrid"
    base_ids = [
        component["component_id"]
        for component in components
        if component["layer_role"] == "base"
    ]
    return {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 1,
        "mode": mode,
        "composition": {
            "family": {
                "none": "no_broll",
                "single": "single_full_frame",
                "hybrid": "evidence_with_data_overlay",
            }[mode],
            "presenter_mode": "full_frame" if mode == "none" else "bottom_window",
            "reading_order": [component["component_id"] for component in components],
            "component_dependencies": [
                {
                    "component_id": component["component_id"],
                    "depends_on": base_ids,
                }
                for component in components
                if component["layer_role"] == "annotation"
            ],
        },
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }


class BrollMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.job = _Job(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_media(self, relative: str, payload: bytes) -> Path:
        source = self.job.job_dir / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(payload)
        return source

    def _frozen_component(
        self,
        component_id: str,
        kind: str,
        relative: str,
        payload: bytes,
        *,
        index: int = 0,
        media_type: str | None = None,
    ) -> tuple[dict[str, object], Path]:
        source = self._write_media(relative, payload)
        component = _component(
            component_id,
            kind,
            path=relative,
            index=index,
            media_type=media_type,
        )
        component["sha256"] = _sha256(source)
        return component, source

    def test_hybrid_resolves_every_component_in_recipe_order_without_mutation(self) -> None:
        stock, stock_path = self._frozen_component(
            "stock", "external_stock", "frozen/stock.mp4", b"stock", index=0
        )
        code = _component("code", "code_generated", index=1)
        official, official_path = self._frozen_component(
            "official",
            "official_material",
            "00-user-provided/official.pdf",
            b"official",
            index=2,
            media_type="document",
        )
        ai = _component("ai", "ai_generated", index=3)
        local, local_path = self._frozen_component(
            "local", "local_material", "00-user-provided/local.png", b"local", index=4
        )
        recipe = _recipe([stock, code, official, ai, local])
        original = copy.deepcopy(recipe)

        resolved = broll_media.resolve_recipe_media(self.job, recipe)

        self.assertIsInstance(resolved, tuple)
        self.assertEqual(
            [item.component_id for item in resolved],
            ["stock", "code", "official", "ai", "local"],
        )
        self.assertEqual(
            [item.kind for item in resolved],
            [
                "external_stock",
                "code_generated",
                "official_material",
                "ai_generated",
                "local_material",
            ],
        )
        self.assertEqual(resolved[0].path, str(stock_path))
        self.assertEqual(resolved[2].path, str(official_path))
        self.assertEqual(resolved[2].media_type, "document")
        self.assertEqual(resolved[4].path, str(local_path))
        self.assertEqual(resolved[2].kind, "official_material")
        self.assertEqual(resolved[2].provenance["publisher"], "Example Institute")
        self.assertEqual(recipe, original)
        with self.assertRaises(FrozenInstanceError):
            resolved[0].path = "replacement.mp4"
        with self.assertRaises(TypeError):
            resolved[0].provenance["status"] = "changed"

    def test_generated_components_are_explicitly_pending_without_placeholders(self) -> None:
        resolved = broll_media.resolve_recipe_media(
            self.job,
            _recipe(
                [
                    _component("code", "code_generated"),
                    _component("ai", "ai_generated", index=1),
                ]
            ),
        )

        self.assertEqual(len(resolved), 2)
        for item in resolved:
            with self.subTest(kind=item.kind):
                self.assertIsNone(item.path)
                self.assertIsNone(item.sha256)
                self.assertEqual(item.provenance["status"], "pending_execution")
        self.assertEqual(resolved[0].provenance["dependency_id"], "html-video")
        self.assertEqual(resolved[1].provenance["generation_id"], "generation-001")

    def test_none_and_generated_only_recipes_do_not_touch_the_filesystem(self) -> None:
        recipes = (
            _recipe([]),
            _recipe([_component("code", "code_generated")]),
            _recipe([_component("ai", "ai_generated")]),
        )
        inaccessible_job = SimpleNamespace()
        for recipe in recipes:
            with self.subTest(mode=recipe["mode"], kinds=[
                component["kind"] for component in recipe["components"]
            ]), mock.patch.object(
                broll_media.os, "lstat", side_effect=AssertionError("filesystem access")
            ) as lstat, mock.patch.object(
                broll_media.os, "open", side_effect=AssertionError("filesystem access")
            ) as open_file:
                resolved = broll_media.resolve_recipe_media(inaccessible_job, recipe)
            lstat.assert_not_called()
            open_file.assert_not_called()
            self.assertEqual(len(resolved), len(recipe["components"]))

    def test_each_frozen_material_kind_uses_job_media_and_approved_media_type(self) -> None:
        cases = (
            ("local_material", "inputs/local.bin", "ui_capture"),
            ("official_material", "inputs/official.bin", "webpage"),
            ("external_stock", "inputs/stock.bin", "video"),
        )
        for kind, relative, media_type in cases:
            with self.subTest(kind=kind):
                component, source = self._frozen_component(
                    "component-1", kind, relative, kind.encode(), media_type=media_type
                )
                resolved = broll_media.resolve_recipe_media(
                    self.job, _recipe([component])
                )[0]
                self.assertEqual(resolved.path, str(source))
                self.assertEqual(resolved.sha256, _sha256(source))
                self.assertEqual(resolved.media_type, media_type)
                self.assertEqual(resolved.provenance["status"], "frozen_media")
                self.assertEqual(resolved.provenance["byte_size"], source.stat().st_size)

    def test_missing_nonregular_hash_and_size_changes_are_rejected(self) -> None:
        missing = _component(
            "missing", "local_material", path="inputs/missing.png"
        )
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([missing]))

        directory = self.job.job_dir / "inputs/directory"
        directory.mkdir(parents=True)
        nonregular = _component(
            "directory", "local_material", path="inputs/directory"
        )
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([nonregular]))

        changed, source = self._frozen_component(
            "changed", "local_material", "inputs/changed.png", b"original"
        )
        source.write_bytes(b"different")
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([changed]))

        resized, source = self._frozen_component(
            "resized", "official_material", "inputs/resized.pdf", b"short"
        )
        source.write_bytes(b"a much longer payload")
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([resized]))

    def test_absolute_parent_and_linked_paths_return_a_stable_error(self) -> None:
        outside = self.root / "outside-name.png"
        outside.write_bytes(b"outside")
        invalid_components = (
            _component("absolute", "local_material", path=str(outside)),
            _component("parent", "local_material", path="../outside-name.png"),
        )
        for component in invalid_components:
            with self.subTest(component=component["component_id"]):
                with self.assertRaises(broll_media.BrollMediaError) as caught:
                    broll_media.resolve_recipe_media(self.job, _recipe([component]))
                self.assertNotIn("outside-name", str(caught.exception))

        linked = self.job.job_dir / "inputs/linked.png"
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(outside)
        component = _component(
            "linked", "local_material", path="inputs/linked.png"
        )
        component["sha256"] = _sha256(outside)
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([component]))

        linked_dir = self.job.job_dir / "linked-dir"
        linked_dir.symlink_to(self.root, target_is_directory=True)
        component = _component(
            "linked-parent", "local_material", path="linked-dir/outside-name.png"
        )
        component["sha256"] = _sha256(outside)
        with self.assertRaises(broll_media.BrollMediaError):
            broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_path_identity_replacement_during_hash_is_rejected(self) -> None:
        component, source = self._frozen_component(
            "replacement", "local_material", "inputs/replacement.bin", b"a" * (2 * 1024 * 1024)
        )
        original_read = os.read
        replaced = False

        def replace_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            chunk = original_read(descriptor, size)
            if chunk and not replaced:
                replaced = True
                old = source.with_suffix(".old")
                source.replace(old)
                source.write_bytes(b"replacement")
            return chunk

        with mock.patch.object(
            broll_media.os, "read", side_effect=replace_after_first_read
        ):
            with self.assertRaises(broll_media.BrollMediaError):
                broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_material_with_any_second_file_alias_is_rejected(self) -> None:
        for second_link in ("inside", "outside"):
            with self.subTest(second_link=second_link):
                relative = f"file-aliases/{second_link}/source.bin"
                component, source = self._frozen_component(
                    f"file-alias-{second_link}",
                    "local_material",
                    relative,
                    b"aliased-media",
                )
                link = (
                    source.with_name("second.bin")
                    if second_link == "inside"
                    else self.root / "outside-file-alias.bin"
                )
                os.link(source, link)
                with self.assertRaises(broll_media.BrollMediaError) as caught:
                    broll_media.resolve_recipe_media(self.job, _recipe([component]))
                self.assertNotIn("outside-file-alias", str(caught.exception))

    def test_second_file_alias_added_during_read_is_rejected(self) -> None:
        component, source = self._frozen_component(
            "alias-change",
            "local_material",
            "inputs/alias-change.bin",
            b"h" * (2 * 1024 * 1024),
        )
        original_read = os.read
        linked = False

        def link_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal linked
            chunk = original_read(descriptor, size)
            if chunk and not linked:
                linked = True
                os.link(source, self.root / "outside-alias-change.bin")
            return chunk

        with mock.patch.object(
            broll_media.os, "read", side_effect=link_after_first_read
        ):
            with self.assertRaises(broll_media.BrollMediaError):
                broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_intermediate_directory_replacement_during_hash_is_rejected(self) -> None:
        component, source = self._frozen_component(
            "directory-change",
            "local_material",
            "inputs/directory-change.bin",
            b"a" * (2 * 1024 * 1024),
        )
        original_read = os.read
        replaced = False

        def replace_parent_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            chunk = original_read(descriptor, size)
            if chunk and not replaced:
                replaced = True
                old_parent = source.parent.with_name("inputs-old")
                source.parent.replace(old_parent)
                source.parent.mkdir()
                source.write_bytes(b"replacement")
            return chunk

        with mock.patch.object(
            broll_media.os, "read", side_effect=replace_parent_after_first_read
        ):
            with self.assertRaises(broll_media.BrollMediaError):
                broll_media.resolve_recipe_media(self.job, _recipe([component]))

    def test_workspace_visible_path_change_is_rejected(self) -> None:
        component, _source = self._frozen_component(
            "ancestor-change",
            "local_material",
            "inputs/ancestor-change.bin",
            b"a" * (2 * 1024 * 1024),
        )
        moved_workspace = self.root.with_name(f"{self.root.name}-outside")
        original_read = os.read
        replaced = False

        def replace_ancestor_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            chunk = original_read(descriptor, size)
            if chunk and not replaced:
                replaced = True
                self.root.rename(moved_workspace)
                self.root.symlink_to(moved_workspace, target_is_directory=True)
            return chunk

        try:
            with mock.patch.object(
                broll_media.os,
                "read",
                side_effect=replace_ancestor_after_first_read,
            ):
                with self.assertRaises(broll_media.BrollMediaError):
                    broll_media.resolve_recipe_media(self.job, _recipe([component]))
        finally:
            if self.root.is_symlink():
                self.root.unlink()
            if moved_workspace.exists():
                moved_workspace.rename(self.root)

    def test_stable_ancestor_chain_is_shared_by_hybrid_materials(self) -> None:
        local, local_path = self._frozen_component(
            "ancestor-local",
            "local_material",
            "inputs/ancestor-local.bin",
            b"local",
        )
        stock, stock_path = self._frozen_component(
            "ancestor-stock",
            "external_stock",
            "stock/ancestor-stock.bin",
            b"stock",
            index=1,
        )
        real_open = os.open
        anchor_opens = 0

        def track_anchor_open(*args: object, **kwargs: object) -> int:
            nonlocal anchor_opens
            if args and args[0] == self.job.job_dir.anchor and "dir_fd" not in kwargs:
                anchor_opens += 1
            return real_open(*args, **kwargs)

        with mock.patch.object(
            broll_media.os, "open", side_effect=track_anchor_open
        ):
            resolved = broll_media.resolve_recipe_media(
                self.job, _recipe([local, stock])
            )

        self.assertEqual([item.path for item in resolved], [str(local_path), str(stock_path)])
        self.assertEqual(anchor_opens, 2)

    def test_success_and_failure_close_every_opened_descriptor(self) -> None:
        valid, _source = self._frozen_component(
            "fd-success",
            "local_material",
            "nested/media/fd-success.bin",
            b"descriptor-success",
        )
        invalid = copy.deepcopy(valid)
        invalid["component_id"] = "fd-failure"
        invalid["sha256"] = "0" * 64
        real_open = os.open
        real_close = os.close

        for component, should_fail in ((valid, False), (invalid, True)):
            with self.subTest(should_fail=should_fail):
                opened: list[int] = []
                closed: list[int] = []

                def tracked_open(*args: object, **kwargs: object) -> int:
                    descriptor = real_open(*args, **kwargs)
                    opened.append(descriptor)
                    return descriptor

                def tracked_close(descriptor: int) -> None:
                    closed.append(descriptor)
                    real_close(descriptor)

                with mock.patch.object(
                    broll_media.os, "open", side_effect=tracked_open
                ), mock.patch.object(
                    broll_media.os, "close", side_effect=tracked_close
                ):
                    if should_fail:
                        with self.assertRaises(broll_media.BrollMediaError):
                            broll_media.resolve_recipe_media(
                                self.job, _recipe([component])
                            )
                    else:
                        broll_media.resolve_recipe_media(
                            self.job, _recipe([component])
                        )
                self.assertTrue(opened)
                self.assertEqual(Counter(closed), Counter(opened))

    def test_hashing_is_chunked_and_does_not_use_path_read_bytes(self) -> None:
        component, source = self._frozen_component(
            "large", "local_material", "inputs/large.bin", b"z" * (3 * 1024 * 1024)
        )
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("not chunked")):
            resolved = broll_media.resolve_recipe_media(
                self.job, _recipe([component])
            )[0]
        self.assertEqual(resolved.sha256, _sha256(source))

    def test_recipe_authority_runs_before_filesystem_and_singular_api_is_removed(self) -> None:
        invalid = _recipe([_component("invalid", "local_material")])
        invalid["schema_version"] = 1
        with mock.patch.object(
            broll_media.visual_strategy,
            "validate_shot_recipe_v2",
            wraps=visual_strategy.validate_shot_recipe_v2,
        ) as authority, mock.patch.object(
            broll_media._PinnedJob, "open"
        ) as pin_job:
            with self.assertRaises(broll_media.BrollMediaError):
                broll_media.resolve_recipe_media(SimpleNamespace(), invalid)
        authority.assert_called_once_with(invalid)
        pin_job.assert_not_called()
        self.assertFalse(hasattr(broll_media, "resolve_shot_media"))
        self.assertFalse(hasattr(broll_media, "ResolvedShotMedia"))
        self.assertNotIn("selected_material_id", inspect.getsource(broll_media))

    def test_invalid_job_is_rejected_before_recipe_media_is_opened(self) -> None:
        invalid_job = SimpleNamespace(job_dir=self.root / "missing-job")
        component = _component("component-1", "local_material")
        real_open = os.open
        real_close = os.close
        opened: list[int] = []
        closed: list[int] = []

        def tracked_open(*args: object, **kwargs: object) -> int:
            descriptor = real_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def tracked_close(descriptor: int) -> None:
            closed.append(descriptor)
            real_close(descriptor)

        with mock.patch.object(
            broll_media.os, "open", side_effect=tracked_open
        ), mock.patch.object(
            broll_media.os, "close", side_effect=tracked_close
        ):
            with self.assertRaises(broll_media.BrollMediaError):
                broll_media.resolve_recipe_media(invalid_job, _recipe([component]))
        self.assertTrue(opened)
        self.assertEqual(Counter(closed), Counter(opened))

if __name__ == "__main__":
    unittest.main()

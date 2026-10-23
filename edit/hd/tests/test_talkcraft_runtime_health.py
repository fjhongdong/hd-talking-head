from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from edit.hd.integrations.talkcraft.check_runtime import (
    ROOT,
    RuntimeCheckError,
    _check_closure_files,
    _check_identity,
    check_runtime,
)


class TalkCraftRuntimeHealthTests(unittest.TestCase):
    def _compatibility_path(self) -> str:
        registry = json.loads((ROOT / "runtime/card-registry.json").read_text(encoding="utf-8"))
        return registry["runtime_compatibility"]["path"]

    def _identity_fixture(self, root: Path) -> Path:
        files = (
            "runtime/render.mjs",
            "runtime/closure-manifest.json",
            "runtime/render-core.mjs",
            "runtime/card-registry.json",
            "runtime/card-semantic-index.json",
            "runtime/card-event-capabilities.json",
            self._compatibility_path(),
        )
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        return root / "runtime"

    def test_live_integration_has_exact_dependencies_and_optional_features(self) -> None:
        result = check_runtime()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["production_runtime"]["remotion"], "4.0.520")
        self.assertFalse(result["production_runtime"]["automatic_upgrade"])
        self.assertTrue(result["upstream_baseline"]["workbench_bidirectional_overrides"])
        self.assertTrue(result["upstream_baseline"]["fish_audio_optional"])

    def test_missing_installed_dependency_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "upstream/runtime").mkdir(parents=True)
            (root / "upstream/workbench/src").mkdir(parents=True)
            (root / "upstream/workbench/scripts").mkdir(parents=True)
            (root / "upstream/scripts").mkdir(parents=True)
            (root / "runtime/package.json").write_text(
                json.dumps({"dependencies": {"remotion": "1.0.0"}}), encoding="utf-8"
            )
            (root / "upstream-manifest.json").write_text("{}", encoding="utf-8")
            (root / "upstream/runtime/package.json").write_text(
                json.dumps({"dependencies": {"remotion": "1.0.0"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeCheckError, "installed missing"):
                check_runtime(root)

    def test_missing_workbench_entrypoint_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("runtime", "subtitles", "aroll-overlay", "qualification-evidence"):
                (root / name).symlink_to(ROOT / name, target_is_directory=True)
            shutil.copy2(ROOT / "upstream-manifest.json", root / "upstream-manifest.json")
            upstream_runtime = root / "upstream/runtime"
            upstream_runtime.mkdir(parents=True)
            shutil.copy2(ROOT / "upstream/runtime/package.json", upstream_runtime / "package.json")
            with self.assertRaisesRegex(RuntimeCheckError, "workbench"):
                check_runtime(root)

    def test_changed_render_core_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production = self._identity_fixture(root)
            core = production / "render-core.mjs"
            core.write_bytes(core.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeCheckError, "render core differs"):
                _check_identity(root, production)

    def test_stale_card_index_fails_preflight(self) -> None:
        for name in ("card-semantic-index.json", "card-event-capabilities.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                production = self._identity_fixture(root)
                index_path = production / name
                index = json.loads(index_path.read_text(encoding="utf-8"))
                index["registry_sha256"] = "0" * 64
                index_path.write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeCheckError, "differs from the qualified registry"):
                    _check_identity(root, production)

    def test_changed_compatibility_record_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production = self._identity_fixture(root)
            record = root / self._compatibility_path()
            record.write_bytes(record.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeCheckError, "compatibility record identity changed"):
                _check_identity(root, production)

    def test_changed_non_core_closure_file_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "card-dispatch.mjs"
            source.write_bytes(b"approved")
            files = [{
                "path": source.name,
                "sha256": hashlib.sha256(b"approved").hexdigest(),
                "mode": stat.S_IMODE(source.stat().st_mode),
            }]
            _check_closure_files(root, files)
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeCheckError, "closure file identity changed"):
                _check_closure_files(root, files)


if __name__ == "__main__":
    unittest.main()

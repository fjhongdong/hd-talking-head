from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = (
    Path(__file__).parents[1]
    / "integrations"
    / "talkcraft"
    / "render_production_batch_30.py"
).resolve()
SPEC = importlib.util.spec_from_file_location("talkcraft_batch_renderer", SCRIPT)
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class TalkCraftBatchRendererTests(unittest.TestCase):
    def test_media_evidence_uses_verified_file_hash_and_rejects_same_size_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "presenter.webm"
            source.write_bytes(b"actual-a")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            brief = {"media": [{"sha256": digest}]}
            evidence = renderer.build_media_evidence(brief, [source], ["presenter"])
            self.assertEqual(evidence["media"], [{
                "byte_length": 8,
                "media_ref": "media-0",
                "sha256": digest,
                "slot": "presenter",
                "source": "qualification-fixtures/presenter.webm",
            }])
            source.write_bytes(b"actual-b")
            with self.assertRaisesRegex(ValueError, "media sha256 mismatch"):
                renderer.build_media_evidence(brief, [source], ["presenter"])

    def test_resume_requires_exact_identity_and_all_evidence_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "contrast-a.mp4"
            result_path = root / "contrast-a.render.json"
            sheet = root / "contrast-a.contact-sheet.png"
            resume_path = root / "contrast-a.resume.json"
            output.write_bytes(b"video-a")
            sheet.write_bytes(b"sheet-a")
            brief = {
                "card_id": "card-a",
                "render": {"duration_frames": 42, "qualification_id": "q-a"},
            }
            result_path.write_bytes(renderer.canonical_bytes({
                "card_id": "card-a",
                "frame_count": 42,
                "output_sha256": renderer.sha(output),
                "qualification_id": "q-a",
            }))
            expected = {"brief_sha256": "a" * 64, "media_evidence_sha256": "b" * 64}
            resume_path.write_bytes(renderer.canonical_bytes({
                **expected,
                "contact_sheet_sha256": renderer.sha(sheet),
                "output_sha256": renderer.sha(output),
                "render_result_sha256": renderer.sha(result_path),
            }))
            self.assertTrue(renderer.resume_matches(
                output, result_path, sheet, resume_path, brief, expected,
            ))
            output.write_bytes(b"video-b")
            self.assertFalse(renderer.resume_matches(
                output, result_path, sheet, resume_path, brief, expected,
            ))

    def test_case_identity_update_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            (runtime / "qualification-cases").mkdir()
            (runtime / "src" / "cards").mkdir(parents=True)
            card_id = "alt-block-lines"
            (runtime / "src" / "cards" / f"{card_id}.tsx").write_text("card", encoding="utf-8")
            contract_cue = {
                "cueId": "cue-a", "frame": 1, "anchor": "cue-a", "name": "click",
                "assetKey": "click", "volume": 0.2, "playbackRate": 1.0,
            }
            (runtime / "src" / "cards" / f"{card_id}.contract.json").write_text(
                json.dumps({"sfx_cues": [contract_cue]}), encoding="utf-8",
            )
            case_path = runtime / "qualification-cases" / f"{card_id}.json"
            case_path.write_text(json.dumps({"cases": [{"scene_inputs": [], "sfx": [{
                "anchor": "cue-a", "assetKey": "click", "cueId": "cue-a", "frame": 1,
                "name": "click", "playbackRate": 1.0, "sha256": "a" * 64,
                "src": "qualification/click.mp3", "volume": 0.2,
            }]}]}), encoding="utf-8")
            with mock.patch.object(renderer, "BATCH", (card_id,)):
                renderer.update_case_identities(runtime)
                first = case_path.read_bytes()
                renderer.update_case_identities(runtime)
            self.assertEqual(first, case_path.read_bytes())
            updated = json.loads(first)
            stripped = {key: value for key, value in updated["cases"][0]["sfx"][0].items() if key not in {"src", "sha256"}}
            self.assertEqual(list(stripped), list(contract_cue))

    def test_case_identity_update_rejects_the_canonical_runtime(self) -> None:
        with self.assertRaisesRegex(ValueError, "isolated runtime copy"):
            renderer.update_case_identities(renderer.RUNTIME)

    def test_resume_identity_covers_card_contract_and_common_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            (runtime / "src" / "cards").mkdir(parents=True)
            (runtime / "src" / "production-adapters").mkdir(parents=True)
            card_id = "card-a"
            for relative, contents in (
                (f"src/cards/{card_id}.contract.json", "contract-a"),
                (f"src/production-adapters/{card_id}.ts", "adapter-a"),
                ("closure-manifest.json", "closure-a"),
                ("render.mjs", "render-a"),
            ):
                (runtime / relative).write_text(contents, encoding="utf-8")
            brief = {
                "card_id": card_id,
                "registry": {"sha256": "r" * 64},
                "render": {
                    "duration_frames": 42,
                    "implementation_sha256": "i" * 64,
                    "qualification_id": "q-a",
                },
            }
            before = renderer.build_resume_identity(runtime, brief, "contrast-a", b"brief", b"media")
            (runtime / "src" / "cards" / f"{card_id}.contract.json").write_text("contract-b", encoding="utf-8")
            contract_changed = renderer.build_resume_identity(runtime, brief, "contrast-a", b"brief", b"media")
            self.assertNotEqual(before["contract_sha256"], contract_changed["contract_sha256"])
            (runtime / "closure-manifest.json").write_text("closure-b", encoding="utf-8")
            closure_changed = renderer.build_resume_identity(runtime, brief, "contrast-a", b"brief", b"media")
            self.assertNotEqual(contract_changed["runtime_closure_sha256"], closure_changed["runtime_closure_sha256"])
            (runtime / "render.mjs").write_text("render-b", encoding="utf-8")
            entrypoint_changed = renderer.build_resume_identity(runtime, brief, "contrast-a", b"brief", b"media")
            self.assertNotEqual(closure_changed["runtime_entrypoint_sha256"], entrypoint_changed["runtime_entrypoint_sha256"])

    def test_bootstrap_registry_only_writes_the_supplied_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            live = root / "live"
            copied = root / "copied"
            for runtime in (live, copied):
                (runtime / "src" / "cards").mkdir(parents=True)
                (runtime / "src" / "production-adapters").mkdir(parents=True)
                (runtime / "src" / "cards" / "card-a.tsx").write_text("card", encoding="utf-8")
                (runtime / "src" / "production-adapters" / "card-a.ts").write_text("adapter", encoding="utf-8")
                (runtime / "card-registry.json").write_text(json.dumps({
                    "registry_version": "test",
                    "qualification_policy": {"state": "unqualified", "production_enabled": False},
                    "cards": [{
                        "card_id": "card-a",
                        "production": {"status": "pending", "production_role": "segment"},
                    }, {
                        "card_id": "card-b",
                        "production": {"status": "pending", "production_role": "segment"},
                    }],
                }), encoding="utf-8")
            live_before = (live / "card-registry.json").read_bytes()
            renderer.bootstrap_registry(
                copied, root / "evidence", "targeted-r1", ("card-a",),
            )
            self.assertEqual(live_before, (live / "card-registry.json").read_bytes())
            copied_registry = json.loads((copied / "card-registry.json").read_text(encoding="utf-8"))
            self.assertEqual(copied_registry["cards"][0]["production"]["status"], "qualified")
            self.assertEqual(copied_registry["cards"][1]["production"]["status"], "pending")

    def test_batch_evidence_root_rejects_path_escape(self) -> None:
        for value in (".", "..", "../escape", "/tmp/escape", "nested/escape", ""):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "safe path segment"):
                renderer.evidence_batch_root(value)
        expected = (renderer.EVIDENCE / "card-a" / "targeted-r1").resolve()
        self.assertEqual(renderer.evidence_batch_root("targeted-r1", "card-a"), expected)


if __name__ == "__main__":
    unittest.main()

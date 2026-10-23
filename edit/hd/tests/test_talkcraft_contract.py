from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from edit.hd.tools import contract_artifacts, talkcraft_contract as contract

ROOT = Path(__file__).resolve().parents[3]


def brief() -> dict[str, object]:
    registry = contract.load_card_registry()
    registry_card = registry["cards"][0]
    production = registry_card["production"]
    return {
        "schema_version": "talkcraft-production-brief/v1",
        "card_id": registry_card["card_id"],
        "registry": {
            "version": registry["registry_version"],
            "sha256": contract_artifacts.sha256_file(contract.DEFAULT_CARD_REGISTRY),
        },
        "owner": {
            "type": "span",
            "id": "span-001",
            "chunk_id": "chunk-001",
            "visual_plan_sha256": "d" * 64,
            "spec_sha256": "e" * 64,
            "scene_brief_sha256": "f" * 64,
        },
        "execution_target": {
            "kind": "component",
            "segment_id": "seg-001",
            "component_id": "component-1",
        },
        "content_item_ids": ["idea-001"],
        "text": {"spoken": "这是口播读法。", "display": "这是显示文字"},
        "numbers": [{"raw": 108, "display": "108", "unit": "张"}],
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "frame_scope": {
            "global_start_frame": 0,
            "global_end_frame": 72,
            "span_start_frame": 0,
            "span_end_frame": 72,
            "scene_duration_frames": 72,
            "enter_frames": 8,
            "exit_frames": 8,
        },
        "events": [
            {"anchor_id": "word-001", "type": "text", "frame": 8, "payload": {"text": "108"}},
            {"anchor_id": "sfx-001", "type": "sfx", "frame": 8, "payload": {"cue": "tick"}},
        ],
        "media": [{
            "job_path": "00-user-provided/source.mp4",
            "sha256": "a" * 64,
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "start_frame": 0,
            "end_frame": 72,
            "source_kind": "local_material",
            "authorization_ref": "user-provided/source.json",
        }],
        "style": {
            "theme": "apple-dark",
            "background": "mesh-flow-dark",
            "frame": "hairline",
            "layout": "portrait-safe",
            "max_scale": 1.0,
            "presenter_safe_zone": {"top": 120, "bottom": 360, "left": 48, "right": 48},
        },
        "presentation_kind": "redrawn_illustration",
        "render": {
            "dependency_id": contract.DEPENDENCY_ID,
            "entrypoint": production["derived_entrypoint"],
            "implementation_sha256": production["implementation_sha256"],
            "adapter_version": production["adapter_version"],
            "qualification_id": production["qualification_id"],
            "renderer": contract.PRIMARY_RENDERER,
            "output_media_type": "animation",
            "alpha": True,
            "duration_frames": 72,
        },
    }


class TalkCraftContractTests(unittest.TestCase):
    def test_registry_is_exactly_the_pinned_108_card_set(self) -> None:
        registry = contract.load_card_registry()
        self.assertEqual(len(registry["cards"]), 108)
        self.assertEqual(len({card["card_id"] for card in registry["cards"]}), 108)
        self.assertEqual(
            registry["qualification_policy"],
            {
                "state": "qualified",
                "production_enabled": True,
                "legacy_registry_inherited": False,
            },
        )
        qualified = [
            card for card in registry["cards"]
            if card["production"]["status"] == "qualified"
        ]
        self.assertEqual(len(qualified), 108)
        self.assertEqual(
            [card["card_id"] for card in registry["cards"] if card["production"]["status"] != "qualified"],
            [],
        )

    def test_registry_rebuild_rejects_changed_upstream_card_identity(self) -> None:
        integration = contract.DEFAULT_CARD_REGISTRY.parent.parent
        manifest = json.loads(
            (integration / "upstream-manifest.json").read_text(encoding="utf-8")
        )
        manifest["cards"][0]["upstream"]["source_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            changed_manifest = temporary_root / "manifest.json"
            output = temporary_root / "registry.json"
            changed_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    "node",
                    str(integration / "build_card_registry.mjs"),
                    str(output),
                    str(changed_manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("qualified baseline", completed.stderr)
        self.assertFalse(output.exists())

    def test_fully_qualified_brief_accepts_draft_and_production_validation(self) -> None:
        payload = brief()
        self.assertEqual(
            contract.validate_draft_brief(payload), payload
        )
        self.assertEqual(contract.validate_production_brief(payload), payload)

    def test_parallel_items_qualification_record_binds_the_live_registry(self) -> None:
        evidence = (
            contract.DEFAULT_CARD_REGISTRY.parent.parent
            / "qualification-evidence" / "parallel-items-with-host"
            / "production-pilot-r1" / "qualification-record.json"
        )
        record = json.loads(evidence.read_text(encoding="utf-8"))
        identity_bytes = json.dumps(
            record["identity"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        qualification_id = hashlib.sha256(identity_bytes).hexdigest()
        self.assertEqual(record["qualification_id"], qualification_id)
        adapter_path = ROOT / "skill-development/hd-talking-head/scripts/talkcraft_adapter.py"
        self.assertEqual(
            record["identity"]["adapter_sha256"],
            hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
        )
        self.assertIn(
            f'ADAPTER_VERSION = "{record["identity"]["adapter_version"]}"',
            adapter_path.read_text(encoding="utf-8"),
        )
        qualification_case = json.loads(
            (contract.DEFAULT_CARD_REGISTRY.parent / "qualification-cases" / "parallel-items-with-host.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            qualification_case["adapter_version"],
            record["identity"]["adapter_version"],
        )
        self.assertEqual(
            qualification_case["implementation_sha256"],
            record["identity"]["implementation_sha256"],
        )
        self.assertEqual(
            qualification_case["contract_sha256"],
            record["identity"]["contract_sha256"],
        )
        registry = contract.load_card_registry()
        card = next(
            item for item in registry["cards"]
            if item["card_id"] == "parallel-items-with-host"
        )
        self.assertEqual(card["production"]["qualification_id"], qualification_id)
        self.assertEqual(
            card["production"]["implementation_sha256"],
            hashlib.sha256(
                (contract.DEFAULT_CARD_REGISTRY.parent / "src" / "cards" / "parallel-items-with-host.tsx").read_bytes()
            ).hexdigest(),
        )

    def test_rejects_stale_registry_remote_media_and_oversized_chunk(self) -> None:
        cases = []
        stale = brief()
        stale["registry"]["sha256"] = "f" * 64
        cases.append(stale)
        remote = brief()
        remote["media"][0]["job_path"] = "https://example.com/source.mp4"
        cases.append(remote)
        oversized = brief()
        oversized["frame_scope"].update(global_end_frame=721, span_end_frame=721, scene_duration_frames=721)
        oversized["render"]["duration_frames"] = 721
        cases.append(oversized)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(contract.TalkCraftContractError):
                contract.validate_draft_brief(payload)

    def test_validation_is_pure_and_hash_is_deterministic(self) -> None:
        payload = brief()
        original = copy.deepcopy(payload)
        first = contract.draft_brief_sha256(payload)
        second = contract.draft_brief_sha256(payload)
        self.assertEqual(first, second)
        self.assertEqual(payload, original)

    def test_registry_allows_only_policy_consistent_full_qualification(self) -> None:
        raw = json.loads(contract.DEFAULT_CARD_REGISTRY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            contract_artifacts.write_json_artifact(path, raw)
            self.assertEqual(contract.load_card_registry(path)["cards"][0]["production"]["status"], "qualified")
            raw["cards"][0]["production"] = {
                **raw["cards"][0]["production"],
                "status": "pending_portrait_adapter",
                "derived_entrypoint": None,
                "implementation_sha256": None,
                "input_adapter_sha256": None,
                "adapter_version": None,
                "qualification_id": None,
            }
            contract_artifacts.write_json_artifact(path, raw)
            with self.assertRaisesRegex(contract.TalkCraftContractError, "policy"):
                contract.load_card_registry(path)
            raw["qualification_policy"]["state"] = "partially_qualified"
            contract_artifacts.write_json_artifact(path, raw)
            self.assertEqual(contract.load_card_registry(path)["cards"][0]["production"]["status"], "pending_portrait_adapter")

    def test_draft_bundle_binds_ordered_unique_card_uses(self) -> None:
        first = brief()
        second = copy.deepcopy(first)
        second["execution_target"]["component_id"] = "component-002"
        entries = [
            {
                "brief": item,
                "brief_sha256": contract_artifacts.sha256_json(item),
            }
            for item in (first, second)
        ]
        unsigned = {
            "schema_version": "talkcraft-brief-bundle/v1",
            "owner": copy.deepcopy(first["owner"]),
            "briefs": entries,
        }
        bundle = {
            **unsigned,
            "bundle_sha256": contract_artifacts.sha256_json(unsigned),
        }
        self.assertEqual(contract.validate_draft_brief_bundle(bundle), bundle)
        duplicate = copy.deepcopy(bundle)
        duplicate["briefs"][1] = copy.deepcopy(duplicate["briefs"][0])
        unsigned_duplicate = {
            key: item for key, item in duplicate.items() if key != "bundle_sha256"
        }
        duplicate["bundle_sha256"] = contract_artifacts.sha256_json(unsigned_duplicate)
        with self.assertRaisesRegex(contract.TalkCraftContractError, "unique"):
            contract.validate_draft_brief_bundle(duplicate)


if __name__ == "__main__":
    unittest.main()

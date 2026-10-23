from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INTEGRATION = ROOT / "edit" / "hd" / "integrations" / "talkcraft"
UPSTREAM = INTEGRATION / "upstream"
MANIFEST_PATH = INTEGRATION / "upstream-manifest.json"
PINNED_COMMIT = "ccb8a571f4bd620b5588bef4b264b5120f5042fc"
SKILL_SHA256 = "146b31e1869d2e89e1286cd6b28629b6b8b3bd662bda845510c9dbfbb6cb0a1c"
HANDWRITTEN = {
    "chapter-title-card",
    "count-badge-title",
    "highlighter-sweep",
    "impact-open-title",
}
CATEGORY_COUNTS = {
    "人物互动": 10,
    "字幕花字": 22,
    "强调标注": 14,
    "数据信息图": 14,
    "素材呈现": 27,
    "转场结构": 13,
    "运镜": 8,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TalkCraftUpstreamManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_snapshot_is_the_pinned_licensed_source(self) -> None:
        source = self.manifest["source"]
        self.assertEqual(source["commit"], PINNED_COMMIT)
        self.assertEqual(_sha256(UPSTREAM / "SKILL.md"), SKILL_SHA256)
        self.assertEqual(source["declared_license"], "PolyForm-Noncommercial-1.0.0")
        self.assertEqual(source["commercial_use_status"], "unconfirmed")
        self.assertTrue((UPSTREAM / "LICENSE").is_file())
        self.assertTrue((UPSTREAM / "THIRD_PARTY_NOTICES.md").is_file())

    def test_card_sets_are_exactly_108(self) -> None:
        references = {path.stem for path in (UPSTREAM / "references/cards").glob("*.md")}
        sources = {path.stem for path in (UPSTREAM / "template/cards").glob("*.tsx")}
        demos = {
            path.name
            for path in (UPSTREAM / "demos").iterdir()
            if path.is_dir() and path.name != "_lib" and (path / "index.html").is_file()
        }
        registered = {card["card_id"] for card in self.manifest["cards"]}
        self.assertEqual(len(registered), 108)
        self.assertEqual(references, registered)
        self.assertEqual(sources, registered)
        self.assertEqual(demos, registered)

    def test_workbench_has_104_generated_and_four_handwritten_cards(self) -> None:
        generated = {
            path.stem
            for path in (UPSTREAM / "workbench/src/cards/gen").glob("*.tsx")
            if not path.stem.startswith("kscene-")
        }
        handwritten = {
            card["card_id"]
            for card in self.manifest["cards"]
            if card["workbench_implementation"] == "handwritten"
        }
        self.assertEqual(handwritten, HANDWRITTEN)
        self.assertEqual(len(generated), 104)
        self.assertEqual(generated | handwritten, {card["card_id"] for card in self.manifest["cards"]})
        self.assertEqual(self.manifest["invariants"]["auxiliary_kscene_count"], 23)
        self.assertFalse(self.manifest["invariants"]["auxiliary_kscenes_are_cards"])

    def test_every_card_hash_matches_all_four_upstream_representations(self) -> None:
        for card in self.manifest["cards"]:
            card_id = card["card_id"]
            workbench = (
                f"workbench/src/cards/{card_id}.tsx"
                if card_id in HANDWRITTEN
                else f"workbench/src/cards/gen/{card_id}.tsx"
            )
            expected = {
                "reference_sha256": f"references/cards/{card_id}.md",
                "source_sha256": f"template/cards/{card_id}.tsx",
                "demo_sha256": f"demos/{card_id}/index.html",
                "workbench_sha256": workbench,
            }
            for key, relative_path in expected.items():
                self.assertEqual(card["upstream"][key], _sha256(UPSTREAM / relative_path), relative_path)
            self.assertEqual(card["adaptation"]["status"], "pending_portrait_production_adapter")

    def test_categories_and_auxiliary_libraries_are_not_counted_as_cards(self) -> None:
        self.assertEqual(self.manifest["invariants"]["category_counts"], CATEGORY_COUNTS)
        self.assertEqual(self.manifest["auxiliary"]["backdrops"]["count"], 12)
        self.assertEqual(self.manifest["auxiliary"]["video_frames"]["count"], 8)
        self.assertEqual(self.manifest["invariants"]["production_canvas"], {"width": 1080, "height": 1920, "fps": 24})
        self.assertEqual(self.manifest["auxiliary"]["symlinks"]["count"], 3)
        self.assertEqual(self.manifest["auxiliary"]["symlinks"]["broken_count"], 1)
        self.assertEqual(
            self.manifest["adaptation_summary"]["status"],
            "source_imported_production_adaptation_pending",
        )
        self.assertEqual(
            self.manifest["adaptation_summary"]["signal_counts"]["fixed_landscape_geometry"],
            108,
        )
        self.assertEqual(
            len(self.manifest["adaptation_summary"]["shared_runtime_requirements"]["webgl_backdrops"]),
            5,
        )

    def test_checked_in_manifest_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            regenerated = Path(tmp) / "manifest.json"
            subprocess.run(
                ["node", str(INTEGRATION / "build_upstream_manifest.mjs"), str(regenerated)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(regenerated.read_text(encoding="utf-8")),
                self.manifest,
            )


if __name__ == "__main__":
    unittest.main()

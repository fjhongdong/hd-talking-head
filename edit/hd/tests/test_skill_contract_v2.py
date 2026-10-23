from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = ROOT / "skill-development/hd-talking-head"
CHECKOUT_ROOT = ROOT.parent.parent if ROOT.parent.name == ".worktrees" else ROOT
REFERENCE_ROOT = CHECKOUT_ROOT / "参考项目" / "B-roll开源方案"
SOURCE_KINDS = {
    "local_material",
    "official_material",
    "code_generated",
    "external_stock",
    "ai_generated",
}
SOURCE_POLICY_PATHS = (
    SKILL_ROOT / "SKILL.md",
    SKILL_ROOT / "references" / "broll-capability-router.md",
    SKILL_ROOT / "references" / "job-workspace-contract.md",
    SKILL_ROOT / "references" / "stage-contracts.md",
)
SOURCE_POLICY_BLOCK = re.compile(
    r"```broll-source-policy\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


def _load_router():
    path = SKILL_ROOT / "scripts" / "broll_capability_router.py"
    spec = importlib.util.spec_from_file_location("hd_broll_router_v2_contract", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FullV2SourcePolicyTests(unittest.TestCase):
    def test_authoritative_documents_share_one_exact_policy_block(self) -> None:
        expected_rules = {
            *(f"- `{kind}`" for kind in SOURCE_KINDS),
            "kind_priority: none",
            "selection_mode: none | single | hybrid",
            "semantic_role_source_separation: required",
            "quota: none",
            "cross_kind_replacement: forbidden",
        }
        for path in SOURCE_POLICY_PATHS:
            source = path.read_text(encoding="utf-8")
            blocks = [match.group("body") for match in SOURCE_POLICY_BLOCK.finditer(source)]
            with self.subTest(path=path.name, rule="single-policy-block"):
                self.assertEqual(len(blocks), 1)
            if len(blocks) != 1:
                continue
            lines = {line.strip() for line in blocks[0].splitlines() if line.strip()}
            with self.subTest(path=path.name, rule="exact-policy"):
                self.assertEqual(lines, expected_rules)

    def test_plan_contract_accepts_only_current_visual_schema(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in SOURCE_POLICY_PATHS
        )
        for phrase in (
            "VisualPlan schema v3",
            "ShotRecipe v2",
            "不兼容旧 visual Job",
            "旧 visual Job 重新执行 `visual_direction`",
        ):
            self.assertIn(phrase, combined)


class FullV2DependencyAndAdapterTests(unittest.TestCase):
    def test_all_ten_reference_adapters_have_existing_local_entrypoints(self) -> None:
        router = _load_router()
        self.assertEqual(len(router.CAPABILITY_REGISTRY), 10)
        for name, capability in router.CAPABILITY_REGISTRY.items():
            repository = REFERENCE_ROOT / capability["directory"]
            self.assertTrue(repository.is_dir(), f"missing repository for {name}")
            for entrypoint in capability["entrypoints"]:
                self.assertTrue(
                    (repository / entrypoint).exists(),
                    f"missing entrypoint for {name}: {entrypoint}",
                )

    def test_twenty_formal_families_remain_registered(self) -> None:
        router = _load_router()
        families = {
            family
            for candidates in router.FAMILY_CANDIDATES.values()
            for family in candidates
        }
        formal_families = {
            "proof-scrapbook",
            "official-video",
            "orbit-data",
            "comic-steps",
            "ai-cinema",
            "versus-split",
            "ribbon-timeline",
            "quote-artword",
            "modular-dashboard",
            "newspaper-dossier",
            "filmstrip-storyboard",
            "network-map",
            "bold-number-impact",
            "diagonal-debate",
            "staircase-path",
            "evidence-investigation-wall",
            "magazine-cover",
            "radial-burst",
            "blueprint-system",
            "playful-sticker-board",
        }
        self.assertEqual(len(formal_families), 20)
        self.assertTrue(formal_families.issubset(families))
        self.assertTrue({"official-dossier", "editorial-contrast"}.issubset(families))

    def test_exact_grok_adapter_and_model_are_preserved(self) -> None:
        adapter = (
            SKILL_ROOT / "references" / "open-source-adapter-matrix.md"
        ).read_text(encoding="utf-8")
        self.assertIn('"provider_adapter": "OpenMontage:GrokVideo"', adapter)
        self.assertIn('"model": "grok-imagine-video"', adapter)
        self.assertIn("不使用 `fallback_tools`", adapter)

    def test_code_broll_invokes_registered_dependency_skill(self) -> None:
        production = (
            SKILL_ROOT / "references" / "production-bindings.md"
        ).read_text(encoding="utf-8")
        dependency = (
            SKILL_ROOT / "references" / "dependency-preflight.md"
        ).read_text(encoding="utf-8")
        combined = production + "\n" + dependency
        for phrase in (
            "`code_generated` 调用现有依赖 Skill",
            "ReferenceProcessAdapter",
            "invocation_record",
            "dependency_id",
            "entrypoint",
            "producer_version",
        ):
            self.assertIn(phrase, combined)

    def test_local_canonical_renderer_is_a_bound_conditional_dependency(self) -> None:
        manifest = __import__("json").loads(
            (SKILL_ROOT / "references" / "dependency-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        matches = [
            item
            for item in manifest["dependencies"]
            if item["id"] == "local-canonical-adapter"
        ]
        self.assertEqual(len(matches), 1)
        dependency = matches[0]
        self.assertFalse(dependency["required"])
        self.assertEqual(
            dependency["selection"],
            {
                "component_kind": "code_generated",
                "binding_field": "dependency_id",
                "equals": "hd-talking-head-local-canonical",
                "required_level": "bound",
            },
        )
        self.assertIn("scripts/local_canonical_renderer.cjs", dependency["entrypoints"])
        self.assertIn("scripts/local_canonical_adapter.py", dependency["entrypoints"])
        self.assertIn("package.json", dependency["entrypoints"])


if __name__ == "__main__":
    unittest.main()

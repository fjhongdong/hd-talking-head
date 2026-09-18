#!/usr/bin/env python3
"""Behavior tests for the talking-head dependency preflight."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from edit.hd.tools import contract_artifacts
from edit.hd.tests.test_avatar_contract import avatar_fixture


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "dependency_preflight.py"


def _project_root() -> Path:
    for candidate in (Path(__file__).resolve().parents[4], Path.cwd().resolve()):
        if (candidate / "edit/hd/tools/visual_plan.py").is_file():
            return candidate
    raise RuntimeError("talking-head project root is unavailable")


REPO_ROOT = _project_root()


def _visual_intent() -> dict[str, object]:
    return {
        "segment_id": "seg-001",
        "statement": "Explain the approved idea with semantically matched visuals.",
        "semantic_goals": ["explain"],
        "claims": [{
            "type": "concept",
            "value": "One approved visual explains the idea.",
            "verification_required": False,
        }],
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


def _code_binding(
    dependency_id: str,
    entrypoint: str,
    producer_version: str,
    *,
    executor: str,
    primary_renderer: str,
) -> dict[str, object]:
    return {
        "kind": "code_generated",
        "producer_type": "dependency",
        "dependency_id": dependency_id,
        "entrypoint": entrypoint,
        "producer_version": producer_version,
        "brief_sha256": "4" * 64,
        "invocation_record": {"argv": ["probe", entrypoint], "exit_code": 0},
        "primary_renderer": primary_renderer,
        "renderer_version": producer_version,
        "executor": executor,
        "template_origin": "custom_fallback",
        "template_id": "preflight-fixture",
        "template_version": "1",
        "verification_id": "7" * 64,
        "adaptation_level": "structural",
        "source_entrypoint": "templates/preflight-fixture.html",
        "source_sha256": "8" * 64,
        "sample_sha256": "9" * 64,
        "semantic_families": ["explanation"],
        "capacity": {"min_units": 1, "max_units": 8},
    }


def _stock_binding(provider: str) -> dict[str, object]:
    return {
        "kind": "external_stock",
        "provider": provider,
        "provider_asset_id": "stock-001",
        "author": "Example Author",
        "asset_page": "https://stock.example/assets/stock-001?run=dynamic-value",
        "job_path": "stock/stock-001.mp4",
        "license_snapshot": "licenses/stock-001.html",
        "downloaded_at": "2026-08-31T12:00:00+08:00",
        "sha256": "3" * 64,
    }


def _official_binding(snapshot_path: str) -> dict[str, object]:
    return {
        "kind": "official_material",
        "source_id": "official-video-001",
        "publisher": "Example Institute",
        "source_url": "https://example.org/official-video",
        "snapshot_path": snapshot_path,
        "fetched_at": "2026-09-01T12:00:00+08:00",
        "sha256": "2" * 64,
    }


def _official_binding(snapshot_path: str) -> dict[str, object]:
    return {
        "kind": "official_material",
        "source_id": "official-video-001",
        "publisher": "Example Institute",
        "source_url": "https://example.org/official-video",
        "snapshot_path": snapshot_path,
        "fetched_at": "2026-09-01T12:00:00+08:00",
        "sha256": "2" * 64,
    }


def _complete_visual_plan(
    bindings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    components: list[dict[str, object]] = []
    strategy_components: list[dict[str, object]] = []
    bound_components: dict[str, dict[str, object]] = {}
    candidates: dict[str, list[dict[str, object]]] = {}
    source_summary: dict[str, int] = {}
    for index, raw_binding in enumerate(bindings):
        binding = copy.deepcopy(raw_binding)
        kind = str(binding.pop("kind"))
        executor = str(binding.pop("executor", "stock-adapter"))
        component_id = f"component-{index + 1}"
        layer_role = "base" if index == 0 else "annotation"
        layout_slot = "main" if index == 0 else "annotation"
        source_summary[kind] = source_summary.get(kind, 0) + 1
        strategy_components.append({
            "component_id": component_id,
            "kind": kind,
            "semantic_role": "explanation",
            "layer_role": layer_role,
            "media_type": "animation" if kind == "code_generated" else "video",
            "layout_slot": layout_slot,
            "brief": f"Explain the idea with the approved {kind} component.",
        })
        components.append({
            "component_id": component_id,
            "kind": kind,
            "semantic_role": "explanation",
            "layer_role": layer_role,
            "executor": executor,
            "media_type": "animation" if kind == "code_generated" else "video",
            "render_window": {
                "start_frame": 0,
                "end_frame": 72,
                "z_index": index * 10,
                "layout_slot": layout_slot,
                "opacity": 1.0,
                "safe_zone": {"top": 120, "bottom": 320, "left": 40, "right": 40},
            },
            "artifact_contract": {
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "alpha": kind == "code_generated",
            },
            **copy.deepcopy(binding),
        })
        bound_components[component_id] = copy.deepcopy(binding)
        if kind in {"official_material", "external_stock"}:
            candidates[component_id] = [{
                "asset_id": binding.get("provider_asset_id", binding.get("source_id")),
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

    mode = "single" if len(components) == 1 else "hybrid"
    base_ids = [components[0]["component_id"]]
    composition = {
        "family": "single_full_frame" if mode == "single" else "evidence_with_data_overlay",
        "presenter_mode": "bottom_window",
        "avatar": avatar_fixture(frames=72),
        "reading_order": [component["component_id"] for component in components],
        "component_dependencies": [
            {"component_id": component["component_id"], "depends_on": base_ids}
            for component in components[1:]
        ],
    }
    strategy = {
        "schema_version": 1,
        "segment_id": "seg-001",
        "mode": mode,
        "rationale": "The approved composition explains the intended meaning.",
        "components": strategy_components,
        "composition": copy.deepcopy(composition),
    }
    recipe = {
        "schema_version": 2,
        "segment_id": "seg-001",
        "strategy_revision": 1,
        "mode": mode,
        "composition": copy.deepcopy(composition),
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "components": components,
        "final_compositor": "ffmpeg",
    }
    plan = {
        "schema_version": 3,
        "content_analysis_sha256": "a" * 64,
        "edit_plan_sha256": "b" * 64,
        "timeline_map_sha256": "c" * 64,
        "edited_aroll_sha256": "d" * 64,
        "canvas": {"width": 1080, "height": 1920, "fps": 24},
        "duration": 3.0,
        "segments": [{
            "segment_id": "seg-001",
            "start": 0.0,
            "end": 3.0,
            "content_item_ids": ["idea-01"],
            "visible_text": [],
            "visual_intent": _visual_intent(),
            "visual_strategy": strategy,
            "candidate_snapshots": candidates,
            "bindings": bound_components,
            "shot_recipe": recipe,
        }],
        "source_summary": source_summary,
    }
    return {**plan, "visual_plan_sha256": contract_artifacts.sha256_json(plan)}


def _probe_identity(
    adapter_type: str, approved_executor: str, primary_renderer: str,
) -> dict[str, str]:
    return {
        "adapter_type": adapter_type,
        "approved_executor": approved_executor,
        "primary_renderer": primary_renderer,
    }


def _probe_program(payload: dict[str, object], *, exit_code: int = 0) -> str:
    return (
        "import json\n"
        f"print(json.dumps({payload!r}, sort_keys=True))\n"
        f"raise SystemExit({exit_code})\n"
    )


def _binding_probe(
    entrypoint: str,
    producer_version: str,
    adapter_identity: dict[str, str],
) -> dict[str, object]:
    return {
        "entrypoint": entrypoint,
        "producer_version": producer_version,
        "adapter_identity": adapter_identity,
        "command": ["{python}", "{project_root}/binding_probe.py"],
    }


class DependencyPreflightTests(unittest.TestCase):
    def test_clean_cli_can_probe_a_python_module_without_a_visual_plan(self) -> None:
        result, report = self.run_preflight({
            "schema_version": 1,
            "dependencies": [{
                "id": "module-probe", "kind": "availability_any", "required": True,
                "target": [{"id": "stdlib", "kind": "python_module", "target": "json"}],
            }],
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["dependencies"][0]["status"], "callable")

    def run_project_binding_probe(
        self, runner_source: str,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_root = root / "project"
            tools_root = project_root / "edit" / "hd" / "tools"
            tools_root.mkdir(parents=True)
            for package in (
                project_root / "edit",
                project_root / "edit" / "hd",
                tools_root,
            ):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (tools_root / "broll_component_executor.py").write_text(
                runner_source, encoding="utf-8"
            )

            dependency_root = root / "html-video"
            entrypoint = dependency_root / "adapters" / "render.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("print('render')\n", encoding="utf-8")
            git = shutil.which("git")
            self.assertIsNotNone(git)
            subprocess.run(
                [str(git), "-C", str(dependency_root), "init", "--quiet"],
                check=True,
            )
            subprocess.run(
                [str(git), "-C", str(dependency_root), "add", "."],
                check=True,
            )
            subprocess.run(
                [
                    str(git), "-C", str(dependency_root),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "--quiet", "-m", "fixture",
                ],
                check=True,
            )
            version = subprocess.run(
                [str(git), "-C", str(dependency_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            completed = subprocess.run(
                [
                    str(Path(sys.executable)),
                    str(SCRIPT),
                    "probe-code-binding",
                    "--project-root", str(project_root),
                    "--dependency-root", str(dependency_root),
                    "--dependency-id", "html-video",
                    "--entrypoint", "adapters/render.py",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            return completed, version

    def run_preflight(
        self,
        manifest: dict[str, object],
        *,
        project_files: tuple[str, ...] = (),
        project_contents: dict[str, str] | None = None,
        reference_files: tuple[str, ...] = (),
        skill_names: tuple[str, ...] = (),
        visual_plan: dict[str, object] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_root = root / "project"
            project_root.mkdir()
            if visual_plan is not None:
                # Validate with this fixture's real runtime, never a foreign
                # module imported through the parent process's PYTHONPATH.
                for source in (REPO_ROOT / "edit/hd/tools").rglob("*.py"):
                    target = project_root / source.relative_to(REPO_ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                router = project_root / ".agents/skills/hd-talking-head/scripts/broll_capability_router.py"
                router.parent.mkdir(parents=True)
                shutil.copy2(SKILL_ROOT / "scripts/broll_capability_router.py", router)
            for relative in project_files:
                path = project_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            for relative, content in (project_contents or {}).items():
                path = project_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            if (project_root / "edit").exists():
                for relative in ("edit", "edit/hd", "edit/hd/tools"):
                    package = project_root / relative
                    package.mkdir(parents=True, exist_ok=True)
                    (package / "__init__.py").touch()

            reference_root = root / "references"
            reference_root.mkdir()
            for relative in reference_files:
                path = reference_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# executable fixture\n" if path.suffix == ".py" else "fixture\n", encoding="utf-8")

            skill_root = root / "skills"
            skill_root.mkdir()
            for name in skill_names:
                path = skill_root / name
                path.mkdir()
                (path / "SKILL.md").write_text("---\nname: fixture\n---\n", encoding="utf-8")

            manifest_path = root / "dependencies.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            output_path = root / "report.json"
            command = [
                sys.executable,
                str(SCRIPT),
                "--manifest",
                str(manifest_path),
                "--project-root",
                str(project_root),
                "--reference-root",
                str(reference_root),
                "--skill-root",
                str(skill_root),
                "--output",
                str(output_path),
            ]
            if visual_plan is not None:
                visual_plan_path = root / "visual-plan.json"
                visual_plan_path.write_text(
                    json.dumps(visual_plan, ensure_ascii=False),
                    encoding="utf-8",
                )
                command.extend(("--visual-plan", str(visual_plan_path)))
            environment = dict(os.environ)
            python_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(REPO_ROOT), *(value for value in (python_path,) if value)]
            )
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            report = (
                json.loads(output_path.read_text(encoding="utf-8"))
                if output_path.exists()
                else {}
            )
            return completed, report

    def test_missing_required_dependency_blocks_and_returns_one_install_action(self) -> None:
        manifest = {
            "schema_version": 1,
            "dependencies": [
                {
                    "id": "missing-runtime",
                    "kind": "command",
                    "required": True,
                    "target": "definitely-not-a-real-command-hd-preflight",
                    "install": {
                        "method": "system-package",
                        "package": "fixture-runtime",
                        "approval_required": True,
                    },
                }
            ],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["summary"]["status"], "blocked_missing_required")
        self.assertEqual(report["summary"]["required_missing"], 1)
        self.assertEqual(report["install_plan"][0]["dependency_ids"], ["missing-runtime"])
        self.assertTrue(report["install_plan"][0]["approval_required"])

    def test_optional_gap_is_reported_without_blocking(self) -> None:
        manifest = {
            "schema_version": 1,
            "dependencies": [
                {
                    "id": "python",
                    "kind": "command",
                    "required": True,
                    "target": str(Path(sys.executable)),
                },
                {
                    "id": "optional-reference",
                    "kind": "reference_path",
                    "required": False,
                    "target": "optional-reference",
                },
            ],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["summary"]["status"], "ready_with_optional_gaps")
        self.assertEqual(report["summary"]["required_missing"], 0)
        self.assertEqual(report["summary"]["optional_missing"], 1)

    def test_command_with_nonzero_probe_is_not_callable(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "non-callable-command",
                "kind": "command",
                "required": True,
                "target": str(Path(sys.executable)),
                "version_args": ["-c", "raise SystemExit(7)"],
            }],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertEqual(dependency["status"], "unavailable")
        self.assertFalse(dependency["callable"])

    def test_builtin_binding_probe_returns_runtime_adapter_identity(self) -> None:
        runner_source = """\
from dataclasses import dataclass

_DEPENDENCY_CONTRACTS = {"html-video": ("reference_adapter", "HyperFrames")}

@dataclass(frozen=True)
class ReferenceProcessAdapter:
    adapter_id: str
    dependency_id: str
    approved_executor: str
    dependency_root: object
    entrypoint: str
    entrypoint_sha256: str
    producer_version: str
    primary_renderer: str
    renderer_version: str
    artifact_media_type: str
    launcher: object
    launcher_sha256: str
    argv_template: tuple
    brief_loader: object
    self_contained_wrapper: bool

def _validate_code_adapter():
    return None

def execute_component():
    return None

def _run_reference_process():
    return None
"""

        completed, version = self.run_project_binding_probe(runner_source)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {
            "schema_version": 1,
            "dependency_id": "html-video",
            "entrypoint": "adapters/render.py",
            "producer_version": version,
            "adapter_identity": _probe_identity(
                "ReferenceProcessAdapter", "reference_adapter", "HyperFrames"
            ),
        })

    def test_builtin_hyperframes_probe_requires_the_pinned_runtime(self) -> None:
        runner_source = """\
from dataclasses import dataclass

_DEPENDENCY_CONTRACTS = {"hyperframes": ("reference_adapter", "HyperFrames")}

@dataclass(frozen=True)
class ReferenceProcessAdapter:
    adapter_id: str
    dependency_id: str
    approved_executor: str
    dependency_root: object
    entrypoint: str
    entrypoint_sha256: str
    producer_version: str
    primary_renderer: str
    renderer_version: str
    artifact_media_type: str
    launcher: object
    launcher_sha256: str
    argv_template: tuple
    brief_loader: object
    self_contained_wrapper: bool

def _validate_code_adapter():
    return None

def execute_component():
    return None

def _run_reference_process():
    return None
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_root = root / "project"
            tools_root = project_root / "edit" / "hd" / "tools"
            tools_root.mkdir(parents=True)
            for package in (project_root / "edit", project_root / "edit/hd", tools_root):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (tools_root / "broll_component_executor.py").write_text(
                runner_source, encoding="utf-8"
            )

            skill_root = root / "hd-talking-head"
            entrypoint = skill_root / "scripts/render_hyperframes_notification.cjs"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("'use strict';\n", encoding="utf-8")

            runtime = root / "hyperframes"
            (runtime / "packages/cli/src").mkdir(parents=True)
            (runtime / "node_modules/tsx/dist").mkdir(parents=True)
            (runtime / "packages/cli/package.json").write_text(
                json.dumps({"name": "@hyperframes/cli", "version": "0.8.19"}),
                encoding="utf-8",
            )
            (runtime / "packages/cli/src/cli.ts").write_text("// cli\n", encoding="utf-8")
            (runtime / "node_modules/tsx/dist/cli.mjs").write_text("// tsx\n", encoding="utf-8")
            git = shutil.which("git")
            self.assertIsNotNone(git)
            subprocess.run([str(git), "-C", str(runtime), "init", "--quiet"], check=True)
            subprocess.run([str(git), "-C", str(runtime), "add", "."], check=True)
            subprocess.run([
                str(git), "-C", str(runtime), "-c", "user.name=Fixture",
                "-c", "user.email=fixture@example.invalid", "commit", "--quiet",
                "-m", "fixture",
            ], check=True)
            revision = subprocess.run(
                [str(git), "-C", str(runtime), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            command = [
                sys.executable, str(SCRIPT), "probe-code-binding",
                "--project-root", str(project_root),
                "--dependency-root", str(skill_root),
                "--dependency-id", "hyperframes",
                "--entrypoint", "scripts/render_hyperframes_notification.cjs",
                "--producer-version", "1.0.0",
                "--runtime-root", str(runtime),
                "--runtime-revision", revision,
                "--renderer-version", "0.8.19",
            ]

            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["producer_version"], "1.0.0")

            (runtime / "node_modules/tsx/dist/cli.mjs").unlink()
            missing = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 3)
            self.assertIn("incomplete or has drifted", missing.stderr)

    def test_builtin_binding_probe_rejects_an_empty_adapter_class(self) -> None:
        runner_source = """\
_DEPENDENCY_CONTRACTS = {"html-video": ("reference_adapter", "HyperFrames")}

class ReferenceProcessAdapter:
    pass

def _validate_code_adapter():
    return None

def execute_component():
    return None

def _run_reference_process():
    return None
"""

        completed, _version = self.run_project_binding_probe(runner_source)

        self.assertEqual(completed.returncode, 3)
        self.assertIn("no executable adapter", completed.stderr)

    def test_builtin_binding_probe_rejects_runner_names_stored_as_strings(self) -> None:
        runner_source = """\
_DEPENDENCY_CONTRACTS = {"html-video": ("reference_adapter", "HyperFrames")}
ReferenceProcessAdapter = "class ReferenceProcessAdapter"
_validate_code_adapter = "def _validate_code_adapter"
execute_component = "def execute_component"
_run_reference_process = "def _run_reference_process"
"""

        completed, _version = self.run_project_binding_probe(runner_source)

        self.assertEqual(completed.returncode, 3)
        self.assertIn("no executable adapter", completed.stderr)

    def test_project_and_skill_dependencies_resolve_from_explicit_roots(self) -> None:
        manifest = {
            "schema_version": 1,
            "dependencies": [
                {
                    "id": "state-engine",
                    "kind": "project_path",
                    "required": True,
                    "target": "edit/hd/tools/state.py",
                },
                {
                    "id": "cover-skill",
                    "kind": "skill",
                    "required": True,
                    "target": "gbro-cover-design",
                },
            ],
        }

        completed, report = self.run_preflight(
            manifest,
            project_files=("edit/hd/tools/state.py",),
            skill_names=("gbro-cover-design",),
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["summary"]["status"], "ready")
        statuses = {item["id"]: item["status"] for item in report["dependencies"]}
        self.assertEqual(statuses, {"state-engine": "available", "cover-skill": "available"})
        self.assertRegex(report["manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_final_approval_runner_is_required_and_probed_before_work(self) -> None:
        source = json.loads((SKILL_ROOT / "references/dependency-manifest.json").read_text())
        matches = [item for item in source["dependencies"] if item["id"] == "final-approval-runner"]
        self.assertEqual(len(matches), 1)
        dependency = matches[0]
        self.assertTrue(dependency["required"])
        self.assertEqual(dependency["api"], ["approve_delivery"])
        manifest = {"schema_version": 1, "dependencies": matches}
        for content, expected in ((None, 2), ("approve_delivery = None\n", 2),
                                  ("def approve_delivery(*args, **kwargs): pass\n", 0)):
            with self.subTest(content=content):
                completed, report = self.run_preflight(
                    manifest, project_contents={} if content is None else {dependency["target"]: content},
                )
                self.assertEqual(completed.returncode, expected, completed.stderr)
                self.assertEqual(report["summary"]["status"],
                                 "ready" if expected == 0 else "blocked_missing_required")

    def test_report_records_connection_status_without_environment_contents(self) -> None:
        manifest = {
            "schema_version": 1,
            "dependencies": [
                {
                    "id": "provider-connection",
                    "kind": "environment_any",
                    "required": False,
                    "target": ["HD_PREFLIGHT_TEST_CONNECTION"],
                }
            ],
        }
        connection_value = "runtime-connection-value"

        with mock.patch.dict(
            "os.environ", {"HD_PREFLIGHT_TEST_CONNECTION": connection_value}
        ):
            completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(connection_value, json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["dependencies"][0]["status"], "configured")
        self.assertTrue(report["dependencies"][0]["configured"])
        self.assertFalse(report["dependencies"][0]["connected"])

    def test_reference_directory_is_not_callable_when_entrypoint_is_missing(self) -> None:
        manifest = {
            "schema_version": 2,
            "dependencies": [{
                "id": "video-use-runtime",
                "kind": "reference_path",
                "required": True,
                "stages": ["speech-cleanup", "edit-structure"],
                "target": "video-use",
                "path_type": "directory",
                "capabilities": ["speech.dead-air-edl", "render.segment-fades"],
                "entrypoints": [{
                    "path": "helpers/render.py",
                    "smoke": ["{python}", "{entrypoint}", "--help"],
                }],
            }],
        }

        completed, report = self.run_preflight(
            manifest,
            reference_files=("video-use/SKILL.md",),
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertEqual(dependency["status"], "entrypoint_missing")
        self.assertEqual(dependency["availability_level"], "installed")
        self.assertEqual(report["summary"]["required_missing"], 1)

    def test_callable_dependency_is_not_ready_until_stage_binding_is_proven(self) -> None:
        manifest = {
            "schema_version": 2,
            "dependencies": [{
                "id": "video-use-runtime",
                "kind": "reference_path",
                "required": True,
                "stages": ["speech-cleanup", "edit-structure"],
                "target": "video-use",
                "path_type": "directory",
                "capabilities": ["render.segment-fades"],
                "entrypoints": [{"path": "helpers/render.py", "smoke": ["{python}", "{entrypoint}", "--help"]}],
                "bindings": [{
                    "stage": "edit-structure",
                    "target": "edit/hd/tools/speech_edit_v2.py",
                    "contains_all": ["VIDEO_USE_RENDERER", "video-use-edl.json"],
                }],
            }],
        }

        completed, report = self.run_preflight(
            manifest,
            project_contents={"edit/hd/tools/speech_edit_v2.py": "VIDEO_USE_RENDERER = True\n"},
            reference_files=("video-use/helpers/render.py",),
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertEqual(dependency["status"], "binding_missing")
        self.assertEqual(dependency["availability_level"], "callable")

    def test_bound_dependency_reports_capability_and_stage_coverage(self) -> None:
        manifest = {
            "schema_version": 2,
            "dependencies": [{
                "id": "video-use-runtime",
                "kind": "reference_path",
                "required": True,
                "stages": ["speech-cleanup", "edit-structure"],
                "target": "video-use",
                "path_type": "directory",
                "capabilities": ["speech.dead-air-edl", "render.segment-fades"],
                "entrypoints": [{"path": "helpers/render.py", "smoke": ["{python}", "{entrypoint}", "--help"]}],
                "bindings": [{
                    "stage": "edit-structure",
                    "target": "edit/hd/tools/speech_edit_v2.py",
                    "contains_all": ["VIDEO_USE_RENDERER", "video-use-edl.json"],
                    "api": ["render"],
                }],
            }],
        }

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "edit/hd/tools/speech_edit_v2.py": (
                    "VIDEO_USE_RENDERER = True\nEDL_NAME = 'video-use-edl.json'\ndef render(): pass\n"
                )
            },
            reference_files=("video-use/helpers/render.py",),
        )

        self.assertEqual(completed.returncode, 0)
        dependency = report["dependencies"][0]
        self.assertEqual(dependency["status"], "bound")
        self.assertEqual(dependency["availability_level"], "bound")
        self.assertEqual(
            report["capability_coverage"]["speech.dead-air-edl"]["status"],
            "bound",
        )
        self.assertEqual(report["stage_bindings"][0]["status"], "bound")

    def test_unselected_code_and_stock_dependencies_remain_optional(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [
                {
                    "id": "html-video-runtime",
                    "kind": "reference_path",
                    "required": False,
                    "target": "html-video",
                    "selection": {
                        "component_kind": "code_generated",
                        "binding_field": "dependency_id",
                        "equals": "html-video",
                        "required_level": "bound",
                    },
                },
                {
                    "id": "pexels-provider",
                    "kind": "environment_any",
                    "required": False,
                    "target": ["PEXELS_API_KEY"],
                    "selection": {
                        "component_kind": "external_stock",
                        "binding_field": "provider",
                        "equals": "pexels",
                        "required_level": "connected",
                    },
                },
            ],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["summary"]["required_missing"], 0)
        for dependency in report["dependencies"]:
            self.assertFalse(dependency["selected"])
            self.assertFalse(dependency["required"])

    def test_selected_html_video_requires_exact_executable_binding_probe(self) -> None:
        entrypoint = "adapters/render.py"
        version = "html-video@1.4.2"
        identity = _probe_identity(
            "ReferenceProcessAdapter", "reference_adapter", "HyperFrames"
        )
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "html-video-runtime",
                "kind": "reference_path",
                "required": False,
                "stages": ["visual-canary", "visual-assets"],
                "target": "html-video",
                "path_type": "directory",
                "entrypoints": [entrypoint],
                "binding_probes": [
                    _binding_probe(entrypoint, version, identity)
                ],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "html-video",
                    "required_level": "bound",
                },
            }],
        }
        probe_payload = {
            "schema_version": 1,
            "dependency_id": "html-video",
            "entrypoint": entrypoint,
            "producer_version": version,
            "adapter_identity": identity,
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            entrypoint,
            version,
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "binding_probe.py": _probe_program(probe_payload),
            },
            reference_files=(f"html-video/{entrypoint}",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 0)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertTrue(dependency["callable"])
        self.assertTrue(dependency["bound"])
        self.assertEqual(dependency["entrypoint"], entrypoint)
        self.assertEqual(dependency["version"], version)
        self.assertEqual(dependency["adapter_identity"], identity)

    def test_runner_source_strings_do_not_replace_a_binding_probe(self) -> None:
        entrypoint = "adapters/render.py"
        version = "html-video@1.4.2"
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "html-video-runtime",
                "kind": "reference_path",
                "required": False,
                "target": "html-video",
                "path_type": "directory",
                "entrypoints": [entrypoint],
                "adapter": {
                    "target": "edit/hd/tools/broll_component_executor.py",
                    "contains_all": ["ReferenceProcessAdapter", "html-video"],
                },
                "bindings": [{
                    "stage": "visual-canary",
                    "target": "edit/hd/tools/visual_canary.py",
                    "contains_all": ["execute_component"],
                }],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "html-video",
                    "required_level": "bound",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            entrypoint,
            version,
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "edit/hd/tools/visual_canary.py": "execute_component('html-video')\n",
                "edit/hd/tools/broll_component_executor.py": (
                    "class ReferenceProcessAdapter: pass\n"
                    "html_video = 'html-video execute_component'\n"
                ),
            },
            reference_files=(f"html-video/{entrypoint}",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertFalse(dependency["callable"])
        self.assertFalse(dependency["bound"])
        self.assertEqual(dependency["status"], "binding_probe_unregistered")

    def test_unregistered_producer_version_is_not_promoted_by_source_strings(self) -> None:
        entrypoint = "adapters/render.py"
        approved_version = "html-video@1.4.2"
        registered_version = "html-video@1.4.1"
        identity = _probe_identity(
            "ReferenceProcessAdapter", "reference_adapter", "HyperFrames"
        )
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "html-video-runtime",
                "kind": "reference_path",
                "required": False,
                "target": "html-video",
                "path_type": "directory",
                "entrypoints": [entrypoint],
                "binding_probes": [
                    _binding_probe(entrypoint, registered_version, identity)
                ],
                "adapter": {
                    "target": "edit/hd/tools/broll_component_executor.py",
                    "contains_all": ["ReferenceProcessAdapter", "html-video"],
                },
                "bindings": [{
                    "stage": "visual-canary",
                    "target": "edit/hd/tools/visual_canary.py",
                    "contains_all": ["execute_component", "html-video"],
                }],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "html-video",
                    "required_level": "bound",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            entrypoint,
            approved_version,
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "edit/hd/tools/broll_component_executor.py": (
                    "class ReferenceProcessAdapter: pass\nhtml_video = 'html-video'\n"
                ),
                "edit/hd/tools/visual_canary.py": (
                    "execute_component('html-video')\n"
                ),
            },
            reference_files=(f"html-video/{entrypoint}",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertFalse(dependency["callable"])
        self.assertFalse(dependency["bound"])
        self.assertEqual(dependency["status"], "binding_probe_unregistered")

    def test_binding_probe_identity_must_match_the_approved_recipe(self) -> None:
        entrypoint = "adapters/render.py"
        version = "html-video@1.4.2"
        identity = _probe_identity(
            "ReferenceProcessAdapter", "reference_adapter", "HyperFrames"
        )
        reported_identity = _probe_identity(
            "ReferenceProcessAdapter", "reference_adapter", "AnotherRenderer"
        )
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "html-video-runtime",
                "kind": "reference_path",
                "required": False,
                "target": "html-video",
                "path_type": "directory",
                "entrypoints": [entrypoint],
                "binding_probes": [
                    _binding_probe(entrypoint, version, identity)
                ],
                "adapter": {
                    "target": "edit/hd/tools/broll_component_executor.py",
                    "contains_all": ["ReferenceProcessAdapter", "html-video"],
                },
                "bindings": [{
                    "stage": "visual-canary",
                    "target": "edit/hd/tools/visual_canary.py",
                    "contains_all": ["execute_component", "html-video"],
                }],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "html-video",
                    "required_level": "bound",
                },
            }],
        }
        probe_payload = {
            "schema_version": 1,
            "dependency_id": "html-video",
            "entrypoint": entrypoint,
            "producer_version": version,
            "adapter_identity": reported_identity,
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            entrypoint,
            version,
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "binding_probe.py": _probe_program(probe_payload),
                "edit/hd/tools/broll_component_executor.py": (
                    "class ReferenceProcessAdapter: pass\nhtml_video = 'html-video'\n"
                ),
                "edit/hd/tools/visual_canary.py": (
                    "execute_component('html-video')\n"
                ),
            },
            reference_files=(f"html-video/{entrypoint}",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertFalse(dependency["callable"])
        self.assertFalse(dependency["bound"])
        self.assertEqual(dependency["status"], "binding_probe_mismatch")

    def test_any_code_selection_activates_shared_command_runtime(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "shared-code-runtime",
                "kind": "command",
                "required": False,
                "target": str(Path(sys.executable)),
                "version_args": ["--version"],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "*",
                    "required_level": "callable",
                },
            }],
        }
        visual_plan = _complete_visual_plan((
            _code_binding(
                "html-video", "render.py", "html-video@1",
                executor="reference_adapter", primary_renderer="HyperFrames",
            ),
        ))

        completed, report = self.run_preflight(
            manifest, visual_plan=visual_plan
        )

        self.assertEqual(completed.returncode, 0)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertTrue(dependency["callable"])

    def test_official_video_selects_one_of_download_or_browser_capture(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "official-video-acquisition",
                "kind": "availability_any",
                "required": False,
                "target": [
                    {
                        "id": "yt-dlp-module",
                        "kind": "python_module",
                        "target": "json",
                    },
                    {
                        "id": "browser-capture",
                        "kind": "environment_any",
                        "target": ["HD_BROWSER_CAPTURE_AVAILABLE"],
                    },
                ],
                "selection": {
                    "component_kind": "official_material",
                    "binding_field": "media_type",
                    "equals": "video",
                    "required_level": "callable",
                },
            }],
        }
        visual_plan = _complete_visual_plan((
            _official_binding("official/source.mp4"),
        ))

        completed, report = self.run_preflight(manifest, visual_plan=visual_plan)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertTrue(dependency["callable"])
        self.assertEqual(dependency["selected_alternative"], "yt-dlp-module")

    def test_official_video_blocks_only_when_every_acquisition_path_is_missing(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "official-video-acquisition",
                "kind": "availability_any",
                "required": False,
                "target": [
                    {
                        "id": "missing-module",
                        "kind": "python_module",
                        "target": "module_that_does_not_exist_for_hd_preflight",
                    },
                    {
                        "id": "browser-capture",
                        "kind": "environment_any",
                        "target": ["HD_BROWSER_CAPTURE_AVAILABLE"],
                    },
                ],
                "selection": {
                    "component_kind": "official_material",
                    "binding_field": "media_type",
                    "equals": "video",
                    "required_level": "callable",
                },
            }],
        }
        visual_plan = _complete_visual_plan((
            _official_binding("official/source.mp4"),
        ))

        completed, report = self.run_preflight(manifest, visual_plan=visual_plan)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["summary"]["required_missing"], 1)
        self.assertEqual(report["dependencies"][0]["status"], "missing")

    def test_official_video_selects_one_of_download_or_browser_capture(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "official-video-acquisition",
                "kind": "availability_any",
                "required": False,
                "target": [
                    {
                        "id": "yt-dlp-module",
                        "kind": "python_module",
                        "target": "json",
                    },
                    {
                        "id": "browser-capture",
                        "kind": "environment_any",
                        "target": ["HD_BROWSER_CAPTURE_AVAILABLE"],
                    },
                ],
                "selection": {
                    "component_kind": "official_material",
                    "binding_field": "media_type",
                    "equals": "video",
                    "required_level": "callable",
                },
            }],
        }
        visual_plan = _complete_visual_plan((
            _official_binding("official/source.mp4"),
        ))

        completed, report = self.run_preflight(manifest, visual_plan=visual_plan)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertTrue(dependency["callable"])
        self.assertEqual(dependency["selected_alternative"], "yt-dlp-module")

    def test_official_video_blocks_only_when_every_acquisition_path_is_missing(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "official-video-acquisition",
                "kind": "availability_any",
                "required": False,
                "target": [
                    {
                        "id": "missing-module",
                        "kind": "python_module",
                        "target": "module_that_does_not_exist_for_hd_preflight",
                    },
                    {
                        "id": "browser-capture",
                        "kind": "environment_any",
                        "target": ["HD_BROWSER_CAPTURE_AVAILABLE"],
                    },
                ],
                "selection": {
                    "component_kind": "official_material",
                    "binding_field": "media_type",
                    "equals": "video",
                    "required_level": "callable",
                },
            }],
        }
        visual_plan = _complete_visual_plan((
            _official_binding("official/source.mp4"),
        ))

        completed, report = self.run_preflight(manifest, visual_plan=visual_plan)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["summary"]["required_missing"], 1)
        self.assertEqual(report["dependencies"][0]["status"], "missing")

    def test_selected_code_entrypoint_must_match_manifest_registration(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "html-video-runtime",
                "kind": "reference_path",
                "required": False,
                "target": "html-video",
                "path_type": "directory",
                "entrypoints": ["adapters/render.py"],
                "bindings": [{
                    "stage": "visual-canary",
                    "target": "edit/hd/tools/visual_canary.py",
                    "contains_all": ["execute_component"],
                }],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "html-video",
                    "required_level": "bound",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            "adapters/unregistered.py",
            "html-video@1.4.2",
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "edit/hd/tools/visual_canary.py": "execute_component()\n"
            },
            reference_files=("html-video/adapters/render.py",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            report["dependencies"][0]["status"], "entrypoint_mismatch"
        )

    def test_selected_skill_name_without_callable_adapter_is_not_bound(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "video-shotcraft-skill",
                "kind": "skill",
                "required": False,
                "target": "video-shotcraft",
                "entrypoints": ["SKILL.md"],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "video-shotcraft",
                    "required_level": "bound",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "video-shotcraft",
            "SKILL.md",
            "video-shotcraft@2.0.0",
            executor="skill_invocation",
            primary_renderer="Remotion",
        ),))

        completed, report = self.run_preflight(
            manifest,
            skill_names=("video-shotcraft",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertFalse(dependency["callable"])
        self.assertFalse(dependency["bound"])
        self.assertEqual(dependency["status"], "binding_probe_unregistered")

    def test_selected_video_shotcraft_reports_bound_adapter_identity(self) -> None:
        entrypoint = "SKILL.md"
        version = "video-shotcraft@2.0.0"
        identity = _probe_identity(
            "SkillInvocationAdapter", "skill_invocation", "Remotion"
        )
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "video-shotcraft-skill",
                "kind": "skill",
                "required": False,
                "target": "video-shotcraft",
                "stages": ["visual-canary", "visual-assets"],
                "entrypoints": [entrypoint],
                "binding_probes": [
                    _binding_probe(entrypoint, version, identity)
                ],
                "selection": {
                    "component_kind": "code_generated",
                    "binding_field": "dependency_id",
                    "equals": "video-shotcraft",
                    "required_level": "bound",
                },
            }],
        }
        probe_payload = {
            "schema_version": 1,
            "dependency_id": "video-shotcraft",
            "entrypoint": entrypoint,
            "producer_version": version,
            "adapter_identity": identity,
        }
        visual_plan = _complete_visual_plan((_code_binding(
            "video-shotcraft",
            entrypoint,
            version,
            executor="skill_invocation",
            primary_renderer="Remotion",
        ),))

        completed, report = self.run_preflight(
            manifest,
            project_contents={
                "binding_probe.py": _probe_program(probe_payload),
            },
            skill_names=("video-shotcraft",),
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 0)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertTrue(dependency["callable"])
        self.assertTrue(dependency["bound"])
        self.assertEqual(dependency["entrypoint"], entrypoint)
        self.assertEqual(dependency["version"], version)
        self.assertEqual(dependency["adapter_identity"], identity)

    def test_selected_stock_provider_must_be_connected_before_search(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "pexels-provider",
                "kind": "environment_any",
                "required": False,
                "target": ["PEXELS_API_KEY"],
                "selection": {
                    "component_kind": "external_stock",
                    "binding_field": "provider",
                    "equals": "pexels",
                    "required_level": "connected",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_stock_binding("pexels"),))

        with mock.patch.dict("os.environ", {}, clear=True):
            completed, report = self.run_preflight(
                manifest, visual_plan=visual_plan
            )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertFalse(dependency["connected"])
        self.assertEqual(dependency["status"], "connection_missing")

    def test_unverified_stock_key_is_not_an_authenticated_connection(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "pexels-provider",
                "kind": "environment_any",
                "required": False,
                "target": ["PEXELS_API_KEY"],
                "selection": {
                    "component_kind": "external_stock",
                    "binding_field": "provider",
                    "equals": "pexels",
                    "required_level": "connected",
                },
            }],
        }
        visual_plan = _complete_visual_plan((_stock_binding("pexels"),))
        connection_value = "pexels-runtime-connection"

        with mock.patch.dict(
            "os.environ", {"PEXELS_API_KEY": connection_value}, clear=True
        ):
            completed, report = self.run_preflight(
                manifest, visual_plan=visual_plan
            )

        self.assertEqual(completed.returncode, 2)
        dependency = report["dependencies"][0]
        self.assertTrue(dependency["selected"])
        self.assertFalse(dependency["connected"])
        self.assertTrue(dependency["configured"])
        self.assertEqual(dependency["status"], "connection_missing")
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(connection_value, serialized)
        self.assertNotIn("run=dynamic-value", serialized)

    def test_report_includes_explicit_runtime_binding_fields(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "python",
                "kind": "command",
                "required": True,
                "target": str(Path(sys.executable)),
                "version_args": ["--version"],
            }],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["schema_version"], 3)
        dependency = report["dependencies"][0]
        for field in (
            "selected", "connected", "callable", "bound", "entrypoint", "version"
        ):
            self.assertIn(field, dependency)

    def test_manifest_keeps_stock_providers_static_optional(self) -> None:
        manifest = json.loads(
            (SKILL_ROOT / "references" / "dependency-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        providers = {
            item["id"]: item
            for item in manifest["dependencies"]
            if item["id"] in {"pexels-provider", "pixabay-provider"}
        }

        self.assertEqual(set(providers), {"pexels-provider", "pixabay-provider"})
        for provider in providers.values():
            self.assertFalse(provider["required"])
            self.assertEqual(provider["selection"]["required_level"], "connected")

        by_id = {item["id"]: item for item in manifest["dependencies"]}
        for dependency_id in (
            "node-runtime",
            "npm",
            "html-video-reference",
            "hyperframes-adapter",
            "local-canonical-adapter",
            "video-shotcraft-skill",
        ):
            self.assertFalse(by_id[dependency_id]["required"])
            self.assertIn("selection", by_id[dependency_id])

        expected_probes = {
            "html-video-reference": [(
                "packages/adapter-hyperframes/src/render.ts",
                "c414ecc07f795add03807d5d9ce4baefd807cea2",
                "ReferenceProcessAdapter",
            )],
            "video-shotcraft-skill": [(
                "SKILL.md",
                "c30d78438ef2e8c9cb2b620f19fecff13d982bd3",
                "SkillInvocationAdapter",
            )],
            "hyperframes-adapter": [
                (
                    "scripts/render_hyperframes_notification.cjs",
                    "1.0.0",
                    "ReferenceProcessAdapter",
                ),
                (
                    "scripts/render_hyperframes_chatgpt_exchange.cjs",
                    "1.0.0",
                    "ReferenceProcessAdapter",
                ),
            ],
            "local-canonical-adapter": [(
                "scripts/local_canonical_renderer.cjs",
                "1.0.0",
                "ReferenceProcessAdapter",
            )],
        }
        for dependency_id, expected in expected_probes.items():
            dependency = by_id[dependency_id]
            self.assertNotIn("adapter", dependency)
            self.assertNotIn("bindings", dependency)
            self.assertEqual(len(dependency["binding_probes"]), len(expected))
            actual = {
                (
                    probe["entrypoint"],
                    probe["producer_version"],
                    probe["adapter_identity"]["adapter_type"],
                )
                for probe in dependency["binding_probes"]
            }
            self.assertEqual(actual, set(expected))
            for probe in dependency["binding_probes"]:
                self.assertIn("probe-code-binding", probe["command"])
                if dependency_id in {"hyperframes-adapter", "local-canonical-adapter"}:
                    self.assertIn("--runtime-root", probe["command"])
                    self.assertIn("--runtime-revision", probe["command"])
                    self.assertIn("--renderer-version", probe["command"])

    def test_old_shot_recipe_schema_stops_with_an_explicit_status(self) -> None:
        manifest = {"schema_version": 3, "dependencies": []}
        visual_plan = _complete_visual_plan((_stock_binding("pexels"),))
        visual_plan["segments"][0]["shot_recipe"]["schema_version"] = 1

        completed, report = self.run_preflight(
            manifest, visual_plan=visual_plan
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("visual plan contract validation failed", completed.stderr)

    def test_old_visual_plan_schema_stops_with_an_explicit_status(self) -> None:
        manifest = {"schema_version": 3, "dependencies": []}
        visual_plan = _complete_visual_plan((_stock_binding("pexels"),))
        visual_plan["schema_version"] = 2

        completed, report = self.run_preflight(
            manifest,
            visual_plan=visual_plan,
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("visual plan contract validation failed", completed.stderr)

    def test_incomplete_visual_plan_stops_before_binding_extraction(self) -> None:
        manifest = {"schema_version": 3, "dependencies": []}
        incomplete = {
            "schema_version": 3,
            "segments": [{
                "shot_recipe": {"schema_version": 2, "components": []},
            }],
        }

        completed, report = self.run_preflight(
            manifest, visual_plan=incomplete
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("visual plan contract validation failed", completed.stderr)

    def test_visual_plan_identity_is_checked_before_binding_extraction(self) -> None:
        manifest = {"schema_version": 3, "dependencies": []}
        visual_plan = _complete_visual_plan((_stock_binding("pexels"),))
        visual_plan["visual_plan_sha256"] = "0" * 64

        completed, report = self.run_preflight(
            manifest, visual_plan=visual_plan
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("visual plan contract validation failed", completed.stderr)

    def test_invalid_recipe_component_stops_before_binding_extraction(self) -> None:
        manifest = {"schema_version": 3, "dependencies": []}
        visual_plan = _complete_visual_plan((_code_binding(
            "html-video",
            "adapters/render.py",
            "html-video@1.4.2",
            executor="reference_adapter",
            primary_renderer="HyperFrames",
        ),))
        del visual_plan["segments"][0]["shot_recipe"]["components"][0]["executor"]

        completed, report = self.run_preflight(
            manifest, visual_plan=visual_plan
        )

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("visual plan contract validation failed", completed.stderr)

    def test_selection_contract_rejects_mismatched_component_binding_field(self) -> None:
        manifest = {
            "schema_version": 3,
            "dependencies": [{
                "id": "pexels-provider",
                "kind": "environment_any",
                "required": False,
                "target": ["PEXELS_API_KEY"],
                "selection": {
                    "component_kind": "external_stock",
                    "binding_field": "dependency_id",
                    "equals": "pexels",
                    "required_level": "connected",
                },
            }],
        }

        completed, report = self.run_preflight(manifest)

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report, {})
        self.assertIn("selection values are invalid", completed.stderr)


if __name__ == "__main__":
    unittest.main()

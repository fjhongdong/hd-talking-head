from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    ROOT
    / "skill-development/hd-talking-head"
    / "scripts"
    / "create_job_workspace.py"
)
INITIALIZER_PATH = SCRIPT_PATH.with_name("initialize_video_job.py")
CONTRACT_PATH = (
    ROOT
    / "skill-development/hd-talking-head"
    / "references"
    / "job-workspace-contract.md"
)


def _load_workspace_module():
    spec = importlib.util.spec_from_file_location("hd_create_job_workspace", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_initializer_module():
    spec = importlib.util.spec_from_file_location(
        "hd_initialize_video_job", INITIALIZER_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {INITIALIZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JobWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs_root = self.root / "jobs"
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.video = self.sources / "talking-head.MOV"
        self.image = self.sources / "ceo.png"
        self.duplicate_image = self.sources / "ceo-copy.jpg"
        self.script = self.sources / "script.md"
        self.video.write_bytes(b"video-source")
        self.image.write_bytes(b"same-image-bytes")
        self.duplicate_image.write_bytes(b"same-image-bytes")
        self.script.write_text("一段口播文案", encoding="utf-8")
        self.source_state = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.video, self.image, self.duplicate_image, self.script)
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_new_video_jobs_are_isolated_and_have_complete_directories(self) -> None:
        workspace = _load_workspace_module()
        first = workspace.create_workspace(
            self.jobs_root,
            "真正淘汰你的不是 AI",
            [self.video, self.script, self.image],
        )
        second = workspace.create_workspace(
            self.jobs_root,
            "真正淘汰你的不是 AI",
            [self.video, self.script, self.image],
        )

        self.assertNotEqual(first, second)
        expected = {
            "00-user-provided/video",
            "00-user-provided/images",
            "00-user-provided/audio",
            "00-user-provided/documents",
            "01-inspect",
            "02-content-analysis",
            "03-cover-direction",
            "04-cover",
            "05-speech-cleanup",
            "06-edit-structure",
            "07-visual-direction",
            "08-visual-canary",
            "09-visual-assets/official",
            "09-visual-assets/code",
            "09-visual-assets/ai",
            "09-visual-assets/arroll-overlays",
            "09-visual-assets/avatar",
            "09-visual-assets/segments",
            "10-subtitles",
            "11-preview",
            "12-delivery",
            "manifests",
            "qa",
            "cache",
            "tmp",
        }
        for relative in expected:
            self.assertTrue((first / relative).is_dir(), relative)
            self.assertTrue((second / relative).is_dir(), relative)

    def test_user_files_are_copied_without_modifying_sources(self) -> None:
        workspace = _load_workspace_module()
        job = workspace.create_workspace(
            self.jobs_root,
            "用户资料复制",
            [self.video, self.image, self.script],
        )

        for source, expected in self.source_state.items():
            self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), expected)

        payload = json.loads(
            (job / "00-user-provided/material-index.json").read_text(encoding="utf-8")
        )
        imported = {record["original_name"]: record for record in payload["materials"]}
        for source in (self.video, self.image, self.script):
            target = (job / imported[source.name]["imported_path"]).resolve()
            self.assertTrue(target.is_relative_to(job.resolve()))
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(source.stat().st_nlink, 1)
            self.assertFalse(target.samefile(source))

        target = job / imported[self.video.name]["imported_path"]
        target.write_bytes(b"test-copy-only")
        self.assertEqual(self.video.read_bytes(), b"video-source")

    def test_independent_copy_does_not_overwrite_a_shared_destination(self) -> None:
        workspace = _load_workspace_module()
        with self.assertRaises(FileExistsError):
            workspace.copy_independent_file(self.video, self.video)
        self.assertEqual(self.video.read_bytes(), b"video-source")

    def test_identical_user_files_share_one_imported_asset(self) -> None:
        workspace = _load_workspace_module()
        job = workspace.create_workspace(
            self.jobs_root,
            "资料去重",
            [self.image, self.duplicate_image],
        )

        payload = json.loads(
            (job / "00-user-provided/material-index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["materials"]), 2)
        self.assertEqual(len(payload["assets"]), 1)
        self.assertEqual(
            {record["asset_id"] for record in payload["materials"]},
            {payload["assets"][0]["asset_id"]},
        )
        self.assertEqual(
            {record["imported_path"] for record in payload["materials"]},
            {payload["assets"][0]["imported_path"]},
        )

    def test_formal_initializer_has_one_authoritative_output_tree(self) -> None:
        initializer = _load_initializer_module()

        job, context = initializer.initialize_video_job(
            self.jobs_root,
            "正式全流程",
            self.video,
            self.script,
            [self.image],
        )

        workspace = Path(context["workspace"])
        self.assertEqual(job.job_dir, Path(context["job_dir"]))
        self.assertTrue((job.job_dir / "workflow.json").is_file())
        self.assertTrue((job.job_dir / "12-delivery").is_dir())
        self.assertFalse((workspace / "12-delivery").exists())
        self.assertTrue(
            (workspace / "00-user-provided" / "material-index.json").is_file()
        )
        self.assertEqual(job.version, 2)

    def test_formal_initializer_accepts_deduplicated_same_name_same_bytes(self) -> None:
        initializer = _load_initializer_module()
        first_dir = self.sources / "first"
        second_dir = self.sources / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        primary = first_dir / "same.MOV"
        duplicate = second_dir / "same.MOV"
        primary.write_bytes(b"identical-video")
        duplicate.write_bytes(b"identical-video")

        job, context = initializer.initialize_video_job(
            self.jobs_root,
            "同名同哈希去重",
            primary,
            self.script,
            [duplicate],
        )

        imported = Path(context["video"])
        self.assertTrue(imported.is_file())
        self.assertEqual(imported.read_bytes(), primary.read_bytes())
        self.assertTrue(imported.is_relative_to(Path(context["workspace"])))
        self.assertTrue((job.job_dir / "workflow.json").is_file())

    def test_initializer_cli_works_outside_project_with_explicit_project_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(INITIALIZER_PATH),
                "--project-root",
                str(ROOT),
                "--jobs-root",
                str(self.jobs_root),
                "--title",
                "跨 Agent 启动",
                "--video",
                str(self.video),
                "--script",
                str(self.script),
            ],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)
        self.assertTrue(Path(context["workflow"]).is_file())


class JobWorkspaceContractTests(unittest.TestCase):
    def test_contract_requires_workspace_before_processing_and_one_material_index(self) -> None:
        source = CONTRACT_PATH.read_text(encoding="utf-8")
        for required in (
            "任何分析、下载、生成或渲染之前",
            "00-user-provided",
            "material-index.json",
            "唯一素材索引",
            "不得重新扫描",
            "不得移动、改写或删除用户原文件",
        ):
            self.assertIn(required, source)

    def test_user_material_is_a_traceable_equal_semantic_source(self) -> None:
        source = CONTRACT_PATH.read_text(encoding="utf-8")
        for required in (
            "不设置来源排名",
            "五类同级候选",
            "语义匹配",
            "内容真实性",
            "原生 9:16",
            "未选候选记录中性原因",
            "material_id",
            "精准失效",
            "不触发跨类替换",
        ):
            self.assertIn(required, source)
        self.assertNotIn("用户资料优先", source)


if __name__ == "__main__":
    unittest.main()

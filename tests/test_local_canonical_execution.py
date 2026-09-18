"""Shared local-canonical renderer contract and real low-memory execution."""

from __future__ import annotations

import hashlib
import json
import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
RENDERER = SKILL / "scripts/local_canonical_renderer.cjs"
RUNTIME = Path("/Users/Abner/工作空间/【AI讲师IP内容】/参考项目/B-roll开源方案/hyperframes")
BROWSER = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
COMPOSITIONS = (
    "process-relations",
    "viewpoint-comparison",
    "evidence-source",
    "timeline-progression",
    "quote-thesis-artword",
)
VIDEO_FIXTURE = SKILL / "assets/verified-templates/local-canonical/fixtures/evidence-video.mp4"


def _fixture(composition_id: str, *, variant: int = 1) -> dict[str, object]:
    common = {
        "eyebrow": "核心拆解" if variant == 1 else "方法复盘",
        "title": "真正拉开差距的是什么" if variant == 1 else "团队如何改变工作方式",
        "footer": "把重点放回真实工作场景" if variant == 1 else "从结论走向可执行动作",
        "avatar_image": "",
    }
    specific = {
        "process-relations": {
            "sources": ["决策逻辑", "协作习惯", "行业规则", "经验沉淀"],
            "center": "工作细节",
            "result": "形成隐性能力",
        },
        "viewpoint-comparison": {
            "left": {"label": "表层判断", "headline": "只换工具", "points": ["追逐参数", "复制提示词"]},
            "right": {"label": "深层判断", "headline": "重构流程", "points": ["明确目标", "沉淀方法"]},
            "dimension": "同一问题，两种行动路径",
            "conclusion": "差距来自工作系统",
        },
        "evidence-source": {
            "source_label": "官方资料",
            "media": {
                "kind": "image",
                "data_uri": (
                    "data:image/svg+xml;base64,"
                    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MDAiIGhlaWdodD0iNjAwIj48cmVjdCB3aWR0aD0iODAwIiBoZWlnaHQ9IjYwMCIgZmlsbD0iIzE3MjY0MSIvPjxjaXJjbGUgY3g9IjQwMCIgY3k9IjMwMCIgcj0iMTUwIiBmaWxsPSIjN0RFMEQwIi8+PC9zdmc+"
                ),
                "caption": "研究团队的一线观察",
            },
            "observations": ["问题不只在模型", "流程决定落地效果"],
        },
        "timeline-progression": {
            "stages": [
                {"label": "看见变化", "detail": "识别新标准"},
                {"label": "进入场景", "detail": "完成真实任务"},
                {"label": "沉淀方法", "detail": "形成稳定流程"},
            ],
            "conclusion": "能力在实践中累积",
        },
        "quote-thesis-artword": {
            "thesis": "淘汰你的不是模型",
            "supports": ["而是没有进入真实场景", "也没有沉淀自己的方法"],
        },
    }[composition_id]
    if variant == 2:
        specific = {
            "process-relations": {
                "sources": ["客户信号", "交付数据"],
                "center": "决策系统",
                "result": "形成组织优势",
            },
            "viewpoint-comparison": {
                "left": {"label": "旧式做法", "headline": "堆叠功能", "points": ["增加按钮", "追求数量", "忽略场景", "交付复杂"]},
                "right": {"label": "新式做法", "headline": "解决任务", "points": ["减少步骤", "验证结果", "聚焦用户", "持续复盘"]},
                "dimension": "相同投入，不同用户结果",
                "conclusion": "价值来自任务完成率",
            },
            "evidence-source": {
                "source_label": "项目实录",
                "media": {
                    "kind": "video",
                    "data_uri": "data:video/mp4;base64," + base64.b64encode(
                        VIDEO_FIXTURE.read_bytes()
                    ).decode(),
                    "caption": "试点团队的现场复盘",
                },
                "observations": ["功能数量没有减少阻力", "任务路径才影响转化", "现场复盘持续修正方向"],
            },
            "timeline-progression": {
                "stages": [
                    {"label": "定义问题", "detail": "统一判断标准"},
                    {"label": "验证方案", "detail": "收集真实反馈"},
                    {"label": "规模复制", "detail": "固化交付机制"},
                    {"label": "数据回流", "detail": "补齐使用证据"},
                    {"label": "流程改进", "detail": "修正关键阻力"},
                    {"label": "长期沉淀", "detail": "形成组织方法"},
                ],
                "conclusion": "流程让结果可以复制",
            },
            "quote-thesis-artword": {
                "thesis": "工具不会替你完成改变",
                "supports": ["行动必须进入真实任务", "复盘才能形成长期优势"],
            },
        }[composition_id]
    family = {
        "process-relations": "cause_effect",
        "viewpoint-comparison": "comparison",
        "evidence-source": "evidence",
        "timeline-progression": "progression",
        "quote-thesis-artword": "quote",
    }[composition_id]
    if composition_id == "process-relations":
        units = len(specific["sources"])
    elif composition_id == "viewpoint-comparison":
        units = len(specific["left"]["points"]) + len(specific["right"]["points"])
    elif composition_id == "evidence-source":
        units = len(specific["observations"])
    elif composition_id == "timeline-progression":
        units = len(specific["stages"])
    else:
        units = len(specific["supports"])
    return {
        "schema_version": 1,
        "canvas": {"width": 1080, "height": 1920, "fps": 24, "duration_in_frames": 72},
        "composition_id": composition_id,
        "template_request": {
            "semantic_family": family,
            "information_units": units,
            "numeric_values": [],
            "numeric_scale": "not_applicable",
        },
        "props": {"data": {**common, **specific}},
    }


class LocalCanonicalExecutionTests(unittest.TestCase):
    def validate(self, fixture: dict[str, object]) -> dict[str, object]:
        result = subprocess.run(
            ["node", str(RENDERER), "--validate"],
            input=json.dumps(fixture, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_five_compositions_are_recognized_with_one_strict_contract(self) -> None:
        for composition_id in COMPOSITIONS:
            with self.subTest(composition_id=composition_id):
                checked = self.validate(_fixture(composition_id))
                self.assertEqual(checked["composition_id"], composition_id)
                self.assertEqual(checked["canvas"], {
                    "width": 1080, "height": 1920, "fps": 24,
                    "duration_in_frames": 72,
                })
                self.assertEqual(checked["layout_contract"]["safe_zone"], {
                    "top": 96, "bottom": 210, "left": 64, "right": 64,
                })
                self.assertEqual(checked["layout_contract"]["avatar_slot"], {
                    "x": 796, "y": 1460, "width": 220, "height": 220,
                })
                self.assertEqual(
                    set(checked["action_timeline"]), {"entry", "build", "stable", "exit"},
                )

    def test_unknown_fields_and_over_capacity_text_are_rejected(self) -> None:
        fixture = _fixture("quote-thesis-artword")
        fixture["props"]["data"]["unexpected"] = "do not render"
        result = subprocess.run(
            ["node", str(RENDERER), "--validate"], input=json.dumps(fixture),
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        fixture = _fixture("quote-thesis-artword")
        fixture["props"]["data"]["title"] = "过长标题" * 20
        result = subprocess.run(
            ["node", str(RENDERER), "--validate"], input=json.dumps(fixture),
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_every_visible_string_comes_from_the_brief(self) -> None:
        fixture = _fixture("process-relations")
        checked = self.validate(fixture)
        serialized = json.dumps(fixture["props"]["data"], ensure_ascii=False)
        for visible in checked["visible_text"]:
            self.assertIn(visible, serialized)

    def test_renderer_executes_when_fed_through_frozen_stdin(self) -> None:
        result = subprocess.run(
            ["node", "-", "--brief"],
            input=RENDERER.read_bytes(),
            capture_output=True,
            check=False,
            timeout=10,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"approved local canonical adapter argument order", result.stderr)

    def test_process_and_comparison_actions_follow_semantic_reading_order(self) -> None:
        process = self.validate(_fixture("process-relations"))["action_sequence"]
        self.assertEqual(
            [event["event"] for event in process],
            [
                "source_nodes_visible", "connections_drawing",
                "connections_complete", "center_visible", "result_visible",
            ],
        )
        self.assertEqual(
            [event["at"] for event in process],
            sorted(event["at"] for event in process),
        )
        comparison = self.validate(_fixture("viewpoint-comparison"))["action_sequence"]
        self.assertEqual(
            [event["event"] for event in comparison],
            [
                "left_view_visible", "right_view_visible",
                "dimension_visible", "conclusion_visible",
            ],
        )

    def test_timeline_supports_three_to_six_stages_without_reducing_contract(self) -> None:
        for count in (3, 6):
            fixture = _fixture("timeline-progression")
            fixture["props"]["data"]["stages"] = [
                {"label": f"阶段{index + 1}", "detail": f"完成动作{index + 1}"}
                for index in range(count)
            ]
            fixture["template_request"]["information_units"] = count
            checked = self.validate(fixture)
            self.assertEqual(checked["template_request"]["information_units"], count)

    def test_second_qualification_cases_cover_capacity_and_video_boundaries(self) -> None:
        expected_units = {
            "process-relations": 2,
            "viewpoint-comparison": 8,
            "evidence-source": 3,
            "timeline-progression": 6,
            "quote-thesis-artword": 2,
        }
        for composition_id, units in expected_units.items():
            with self.subTest(composition_id=composition_id):
                checked = self.validate(_fixture(composition_id, variant=2))
                self.assertEqual(checked["template_request"]["information_units"], units)
        evidence = _fixture("evidence-source", variant=2)
        evidence["props"]["data"]["media"]["data_uri"] = _fixture(
            "evidence-source"
        )["props"]["data"]["media"]["data_uri"]
        result = subprocess.run(
            ["node", str(RENDERER), "--validate"],
            input=json.dumps(evidence, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match data.media.kind", result.stderr)

    def test_evidence_video_occupies_the_full_composition_window(self) -> None:
        source = RENDERER.read_text(encoding="utf-8")

        self.assertIn('evidenceMarkup(data, duration)', source)
        self.assertIn('data-duration="${duration}"', source)

    @unittest.skipUnless(RUNTIME.is_dir() and BROWSER.is_file(), "local render runtime unavailable")
    def test_real_render_is_native_muted_animated_and_content_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = []
            for index, fixture in enumerate((
                _fixture("process-relations"),
                _fixture("process-relations"),
                _fixture("process-relations", variant=2),
            )):
                brief = root / f"brief-{index}.json"
                output = root / f"output-{index}.mp4"
                brief.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
                result = subprocess.run([
                    "node", str(RENDERER), "--brief", str(brief), "--output", str(output),
                    "--runtime-root", str(RUNTIME), "--browser", str(BROWSER),
                ], capture_output=True, text=True, check=False, timeout=300)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(output)
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs]
            self.assertEqual(hashes[0], hashes[1])
            self.assertNotEqual(hashes[0], hashes[2])
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                str(outputs[0]),
            ], capture_output=True, text=True, check=True, timeout=30)
            payload = json.loads(probe.stdout)
            streams = payload["streams"]
            video = [stream for stream in streams if stream["codec_type"] == "video"]
            self.assertEqual(len(video), 1)
            self.assertEqual([stream for stream in streams if stream["codec_type"] == "audio"], [])
            self.assertEqual((video[0]["width"], video[0]["height"]), (1080, 1920))
            self.assertEqual(video[0]["r_frame_rate"], "24/1")
            self.assertEqual(video[0].get("tags", {}).get("rotate", "0"), "0")


if __name__ == "__main__":
    unittest.main()
